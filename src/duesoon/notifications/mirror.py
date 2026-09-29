"""Failure-isolated Discord delivery with bounded, submission-safe retries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.intelligence.service import assignment_load_options
from src.duesoon.notifications.discord import DiscordPublishError, DiscordWebhookPublisher
from src.duesoon.persistence.models import Assignment, NotificationDelivery, NotificationMirrorContext


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
            if source is None or source.status not in {"sent", "dry_run"}:
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
            self._finish(delivery_id, "dry_run", None)
            return
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
