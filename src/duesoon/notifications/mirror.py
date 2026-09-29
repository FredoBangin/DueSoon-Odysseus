"""Failure-isolated Discord delivery with bounded, submission-safe retries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.intelligence.service import assignment_load_options
from src.duesoon.notifications.discord import DiscordPublishError, DiscordWebhookPublisher
from src.duesoon.notifications.briefing import school_update
from src.duesoon.persistence.models import (
    Assignment, Course, NotificationDelivery, NotificationMirrorContext, SourceRecord, Submission,
)


logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DiscordMirrorService:
    MAX_ATTEMPTS = 3

    def __init__(
        self, settings: DueSoonSettings, sessions: sessionmaker[Session],
        publisher: DiscordWebhookPublisher | None, *,
        submission_recheck: Callable[[int], str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings, self._sessions, self._publisher = settings, sessions, publisher
        self._recheck, self._clock = submission_recheck, clock

    def recover_pending(self) -> None:
        # A crash after the outbound intent was claimed may have sent the message.
        # Without a confirmed provider ID, never blindly replay that intent.
        with self._sessions() as session:
            session.execute(update(NotificationDelivery).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.status == "pending",
            ).values(status="unknown", error_code="interrupted_outcome", completed_at=self._clock()))
            session.execute(update(NotificationDelivery).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.notification_kind.notin_(("controlled_test", "academic_update", "academic_followup", "daily_digest_preview")),
                NotificationDelivery.status == "retry_scheduled",
            ).values(status="suppressed_policy", error_code="routine_mirroring_disabled", completed_at=self._clock()))
            session.commit()

    def enqueue(
        self, source_id: int, *, assignment_deadlines: dict[int, datetime], expires_at: datetime | None,
    ) -> None:
        try:
            self._enqueue(source_id, assignment_deadlines=assignment_deadlines, expires_at=expires_at)
        except Exception:
            # Never propagate secondary provider errors into the ntfy scheduler.
            # Do not log exception objects: HTTP errors can contain credential URLs.
            logger.error("Discord mirror enqueue failed; primary delivery is unchanged")

    def _enqueue(
        self, source_id: int, *, assignment_deadlines: dict[int, datetime], expires_at: datetime | None,
    ) -> None:
        now = _utc(self._clock())
        with self._sessions() as session:
            source = session.get(NotificationDelivery, source_id)
            if source is None or source.status not in {"sent", "dry_run"} or source.notification_kind != "controlled_test":
                return
            key = f"discord:{source.id}"
            if session.scalar(select(NotificationDelivery.id).where(NotificationDelivery.dedup_key == key)):
                return
            delivery = NotificationDelivery(
                dedup_key=key, notification_kind=source.notification_kind,
                status="retry_scheduled", rendered_title=source.rendered_title,
                rendered_body=source.rendered_body, priority=source.priority,
                provider="discord", attempted_at=now,
            )
            session.add(delivery)
            try:
                session.flush()
                session.add(NotificationMirrorContext(
                    delivery_id=delivery.id, assignment_ids=list(assignment_deadlines),
                    deadline_versions={str(key): _utc(value).isoformat() for key, value in assignment_deadlines.items()},
                    expires_at=expires_at or now + timedelta(minutes=15),
                    next_attempt_at=now, attempts=0,
                ))
                session.commit()
            except IntegrityError:
                session.rollback()
                return
            delivery_id = delivery.id
        self._attempt(delivery_id)

    def run_once(self) -> int:
        if not self._settings.discord_enabled:
            return 0
        with self._sessions() as session:
            ids = session.scalars(select(NotificationDelivery.id).join(
                NotificationMirrorContext,
                NotificationMirrorContext.delivery_id == NotificationDelivery.id,
            ).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.notification_kind == "controlled_test",
                NotificationDelivery.status == "retry_scheduled",
                NotificationMirrorContext.next_attempt_at <= self._clock(),
            ).order_by(NotificationDelivery.id).limit(20)).all()
        for delivery_id in ids:
            self._attempt(delivery_id)
        return len(ids)

    def _attempt(self, delivery_id: int) -> None:
        now = _utc(self._clock())
        with self._sessions() as session:
            context = session.get(NotificationMirrorContext, delivery_id)
            if context is None or _utc(context.next_attempt_at) > now:
                return
            claimed = session.execute(update(NotificationDelivery).where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status == "retry_scheduled",
            ).values(status="pending", attempted_at=now, completed_at=None))
            if claimed.rowcount != 1:
                session.rollback()
                return
            context.attempts += 1
            session.commit()
            delivery = session.get(NotificationDelivery, delivery_id)
            assignment_ids = tuple(context.assignment_ids)
            versions = dict(context.deadline_versions)
            expiry, attempts = _utc(context.expires_at), context.attempts
            title, message, priority, kind = (
                delivery.rendered_title, delivery.rendered_body,
                delivery.priority, delivery.notification_kind,
            )
        if now >= expiry:
            self._finish(delivery_id, "suppressed_stale", "expired")
            return
        if self._settings.dry_run:
            if kind == "daily_digest":
                self._daily_update(delivery_id, assignment_ids, now, {})
            self._finish(delivery_id, "dry_run", None)
            return
        completed_states: dict[int, str] = {}
        if kind == "daily_digest" and self._recheck is not None:
            # Recheck optional completion updates first, then the actual reminders
            # immediately before delivery. A failed optional check never asserts completion.
            for key in self._recent_completion_ids(self._update_window(now), now):
                try:
                    completed_states[key] = self._recheck(key)
                except Exception:
                    completed_states[key] = "unknown"
        if kind != "controlled_test":
            if not assignment_ids or self._recheck is None:
                self._finish(delivery_id, "failed", "missing_recheck_context")
                return
            try:
                states = [self._recheck(assignment_id) for assignment_id in assignment_ids]
            except Exception:
                self._retry(delivery_id, attempts, "submission_recheck_failed")
                return
            with self._sessions() as session:
                context = session.get(NotificationMirrorContext, delivery_id)
                context.submission_rechecked_at = self._clock()
                context.submission_recheck_statuses = {str(key): state for key, state in zip(assignment_ids, states)}
                context.submission_recheck_statuses.update({str(key): state for key, state in completed_states.items()})
                assignments = session.scalars(select(Assignment).options(*assignment_load_options()).where(
                    Assignment.id.in_(assignment_ids)
                )).all()
                current = {str(item.id): project_canvas_assignment(item).operational_due_at for item in assignments if item.published}
                changed = any(
                    key not in current or current[key] is None
                    or _utc(current[key]).isoformat() != deadline
                    for key, deadline in versions.items()
                ) or len(current) != len(assignment_ids)
                session.commit()
            if any(state in {"submitted", "graded"} for state in states):
                self._finish(delivery_id, "suppressed_submission", "completed_since_primary")
                return
            if any(state not in {"not_submitted", "missing", "late"} for state in states):
                self._retry(delivery_id, attempts, "submission_status_unknown")
                return
            if changed or _utc(self._clock()) >= expiry:
                self._finish(delivery_id, "suppressed_stale", "deadline_changed_or_expired")
                return
        if self._publisher is None:
            self._finish(delivery_id, "failed", "provider_disabled")
            return
        if kind == "daily_digest":
            try:
                title, message = self._daily_update(delivery_id, assignment_ids, now, completed_states)
            except Exception:
                self._finish(delivery_id, "failed", "briefing_render_failed")
                return
        try:
            result = self._publisher.publish(title=title, message=message, priority=priority)
        except DiscordPublishError as exc:
            if exc.retryable:
                self._retry(delivery_id, attempts, "provider_transient", exc.retry_after)
            else:
                self._finish(delivery_id, "unknown" if exc.ambiguous else "failed",
                             "ambiguous_outcome" if exc.ambiguous else "provider_error")
        except Exception:
            self._finish(delivery_id, "unknown", "unexpected_provider_outcome")
        else:
            self._finish(delivery_id, "sent", None, result.provider_message_id)

    def _update_window(self, now: datetime) -> datetime:
        with self._sessions() as session:
            previous = session.scalar(select(NotificationDelivery.attempted_at).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.notification_kind == "daily_digest",
                NotificationDelivery.status == "sent",
                NotificationDelivery.attempted_at < now,
            ).order_by(NotificationDelivery.attempted_at.desc()).limit(1))
        return max(now - timedelta(hours=24), _utc(previous)) if previous else now - timedelta(hours=24)

    def _recent_completion_ids(self, start: datetime, now: datetime) -> list[int]:
        with self._sessions() as session:
            recorded = func.coalesce(Submission.submitted_at, Submission.graded_at)
            return list(session.scalars(select(Assignment.id).join(Submission).join(Course).where(
                Course.active.is_(True), Assignment.published.is_(True),
                Submission.normalized_status.in_(("submitted", "graded")),
                recorded > start, recorded <= now,
            ).order_by(recorded.desc(), Assignment.id).limit(3)).all())

    def _daily_update(
        self, delivery_id: int, assignment_ids: tuple[int, ...], now: datetime,
        completed_states: dict[int, str],
    ) -> tuple[str, str]:
        start = self._update_window(now)
        with self._sessions() as session:
            delivery = session.get(NotificationDelivery, delivery_id)
            primary = session.get(NotificationDelivery, int(delivery.dedup_key.split(":", 1)[1]))
            assignments = list(session.scalars(select(Assignment).options(*assignment_load_options()).where(
                Assignment.id.in_(assignment_ids),
            ).order_by(Assignment.id)).all())
            confirmed = [key for key, state in completed_states.items() if state in {"submitted", "graded"}]
            completed = list(session.scalars(select(Assignment).options(*assignment_load_options()).join(Submission).where(
                Assignment.id.in_(confirmed), Submission.normalized_status.in_(("submitted", "graded")),
                func.coalesce(Submission.submitted_at, Submission.graded_at) > start,
                func.coalesce(Submission.submitted_at, Submission.graded_at) <= now,
            ).order_by(func.coalesce(Submission.submitted_at, Submission.graded_at).desc(), Assignment.id)).all())
            # Publication time prevents a first sync of old announcements from
            # being presented as new professor activity. Versions count only once.
            announcements = session.execute(select(SourceRecord.course_id, SourceRecord.external_id).join(Course).where(
                Course.active.is_(True), SourceRecord.source_system == "canvas",
                SourceRecord.source_type == "announcement", SourceRecord.ingestion_status == "ingested",
                SourceRecord.observed_at > start, SourceRecord.observed_at <= now,
                SourceRecord.source_published_at > start, SourceRecord.source_published_at <= now,
            ).distinct()).all()
            title, body = school_update(
                assignments, original_message=primary.rendered_body,
                completed=completed, announcements=len(announcements),
                window_start=start, now=now, timezone=self._settings.timezone,
            )
            delivery.rendered_title, delivery.rendered_body = title, body
            session.commit()
            return title, body

    def _retry(self, delivery_id: int, attempts: int, code: str, retry_after: float | None = None) -> None:
        if attempts >= self.MAX_ATTEMPTS:
            self._finish(delivery_id, "failed", code + "_exhausted")
            return
        delay = max(30 * 2 ** (attempts - 1), retry_after or 0)
        with self._sessions() as session:
            delivery = session.get(NotificationDelivery, delivery_id)
            context = session.get(NotificationMirrorContext, delivery_id)
            if delay >= (_utc(context.expires_at) - _utc(self._clock())).total_seconds():
                delivery.status, delivery.error_code = "suppressed_stale", "retry_after_expiry"
                delivery.completed_at = self._clock()
                session.commit()
                return
            delivery.status, delivery.error_code = "retry_scheduled", code
            context.next_attempt_at = _utc(self._clock()) + timedelta(seconds=delay)
            session.commit()

    def _finish(self, delivery_id: int, status: str, code: str | None, message_id: str | None = None) -> None:
        with self._sessions() as session:
            delivery = session.get(NotificationDelivery, delivery_id)
            delivery.status, delivery.error_code = status, code
            delivery.provider_message_id = message_id
            delivery.completed_at = self._clock()
            session.commit()
