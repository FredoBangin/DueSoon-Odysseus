"""Occasional, evidence-backed Discord updates inside the existing scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import re
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.documents.extract import DocumentExtractionError, extract_document
from src.duesoon.intelligence.service import assignment_load_options
from src.duesoon.notifications.discord import DiscordPublishError, _description
from src.duesoon.notifications.briefing import _date, _label, _text
from src.duesoon.persistence.models import (
    AcademicNote, AcademicUpdateEvent, Assignment, Course, NotificationDelivery,
    NotificationMirrorContext, ReminderEvent, SchedulerState, SourceRecord,
)


logger = logging.getLogger(__name__)
INTERVAL = timedelta(hours=48)
STATE_KEY = "academic_updates_v1"
MAJOR = re.compile(r"\b(exam|midterm|final|project|term paper|test)\b", re.I)
INCOMPLETE = {"not_submitted", "missing", "late"}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _signature(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def announcement_excerpt(source: SourceRecord) -> str:
    """Extract source wording, not AI interpretation; never follow embedded links."""
    payload = source.raw_payload or {}
    body = str(payload.get("message") or payload.get("body") or "")
    body = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", body, flags=re.I | re.S)
    try:
        text = extract_document(body.encode(), filename="announcement.html", content_type="text/html", max_chars=1000).text
    except DocumentExtractionError:
        text = "No readable announcement text; open the source in DueSoon."
    # Contact details, credential-like values, and arbitrary URLs are not needed
    # in a Discord summary. The dashboard retains the original source privately.
    text = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:sk-|AIza)[A-Za-z0-9_-]{15,}", "[redacted]", text)
    return _text(text, 320)


class AcademicUpdateService:
    """Queue meaningful facts; enforce cadence, rechecks, audit, and one follow-up."""

    def __init__(self, settings, sessions, publisher, notifications, *, submission_recheck: Callable[[int], str] | None = None, clock=lambda: datetime.now(UTC)):
        self.settings, self.sessions = settings, sessions
        self.publisher, self.notifications = publisher, notifications
        self.recheck, self.clock = submission_recheck, clock

    def run_once(self) -> int:
        if not self.settings.discord_enabled:
            return 0
        self._discover()
        self._urgent_alerts()
        with self.sessions() as session:
            retry_ids = list(session.scalars(select(NotificationDelivery.id).join(NotificationMirrorContext).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.notification_kind.in_(("academic_update", "academic_followup")),
                NotificationDelivery.status == "retry_scheduled",
                NotificationMirrorContext.next_attempt_at <= self.clock(),
            ).limit(10)).all())
        for key in retry_ids:
            self._attempt(key)
        now = _utc(self.clock())
        with self.sessions() as session:
            last = session.scalar(select(func.max(NotificationDelivery.attempted_at)).where(
                NotificationDelivery.provider == "discord",
                NotificationDelivery.notification_kind.in_(("academic_update", "academic_followup")),
                NotificationDelivery.status.in_(("sent", "unknown", "pending", "retry_scheduled")),
            ))
            if last is not None and now - _utc(last) < INTERVAL:
                return len(retry_ids)
            events = list(session.scalars(select(AcademicUpdateEvent).where(
                AcademicUpdateEvent.status == "pending", AcademicUpdateEvent.discord_delivery_id.is_(None),
            ).order_by(AcademicUpdateEvent.observed_at, AcademicUpdateEvent.id).limit(5)).all())
            followup = False
            if not events:
                followup = True
                events = list(session.scalars(select(AcademicUpdateEvent).where(
                    AcademicUpdateEvent.status == "notified", AcademicUpdateEvent.question.is_not(None),
                    AcademicUpdateEvent.answered_at.is_(None), AcademicUpdateEvent.followup_delivery_id.is_(None),
                    AcademicUpdateEvent.notified_at <= now - INTERVAL,
                ).order_by(AcademicUpdateEvent.notified_at).limit(3)).all())
        if events:
            delivery_id = self._enqueue(events, followup=followup)
            if delivery_id is not None:
                self._attempt(delivery_id)
                return len(retry_ids) + 1
        return len(retry_ids)

    def _discover(self) -> None:
        now = _utc(self.clock())
        with self.sessions() as session:
            state = session.get(SchedulerState, STATE_KEY)
            baseline = state is None
            since = _utc(state.last_successful_at) if state and state.last_successful_at else now
            activation = session.get(SchedulerState, "academic_updates_activation")
            activated_at = _utc(activation.last_successful_at) if activation and activation.last_successful_at else since
            if activation is None:
                session.add(SchedulerState(key="academic_updates_activation", last_successful_at=activated_at))
            assignments = list(session.scalars(select(Assignment).join(Course).options(*assignment_load_options()).where(
                Course.active.is_(True), Assignment.published.is_(True),
            )).all())
            # First activation records a baseline, not a flood of old notices.
            if not baseline:
                sources = session.scalars(select(SourceRecord).join(Course).where(
                    Course.active.is_(True), SourceRecord.source_system == "canvas",
                    SourceRecord.source_type == "announcement", SourceRecord.ingestion_status == "ingested",
                    SourceRecord.observed_at > since, SourceRecord.observed_at <= now,
                ).order_by(SourceRecord.observed_at, SourceRecord.id)).all()
                for source in sources:
                    if source.source_published_at is not None and _utc(source.source_published_at) > now:
                        continue
                    # An edited old announcement is meaningful; a first import of
                    # a historical post is not new professor activity.
                    if source.version == 1 and source.source_published_at is not None and _utc(source.source_published_at) <= activated_at:
                        continue
                    self._add(session, f"announcement:{source.id}", "announcement", _utc(source.observed_at), source_record_id=source.id)
            for assignment in assignments:
                effective = project_canvas_assignment(assignment)
                if effective.submission_status in {"submitted", "graded"}:
                    continue
                due = _utc(effective.operational_due_at) if effective.operational_due_at else None
                facts = {"deadline": due.isoformat() if due else None, "evidence": list(effective.deadline_evidence_ids), "resolution": effective.deadline_status}
                previous = session.scalar(select(AcademicUpdateEvent).where(
                    AcademicUpdateEvent.assignment_id == assignment.id,
                    AcademicUpdateEvent.kind == "deadline_state",
                ).order_by(AcademicUpdateEvent.id.desc()).limit(1))
                before = datetime.fromisoformat(previous.facts["deadline"]) if previous and previous.facts.get("deadline") else None
                changed = previous is not None and previous.facts.get("deadline") != facts["deadline"]
                if previous is None or {key: previous.facts.get(key) for key in facts} != facts:
                    # Operational projections capture professor evidence as well
                    # as Canvas changes. Raw Canvas timestamps do not decide sends.
                    session.add(AcademicUpdateEvent(event_key=f"deadline_state:{assignment.id}:{uuid4()}",
                        kind="deadline_state", assignment_id=assignment.id, facts=dict(facts),
                        observed_at=now, status="baseline"))
                kind, question = None, None
                if effective.deadline_status == "conflicted":
                    kind = "deadline_conflict"
                    facts["candidates"] = [str(value) for value in effective.conflicting_due_at]
                    question = "What did your professor say about the conflicting dates? Share any extra context or the original instruction in this chat."
                elif MAJOR.search(assignment.canonical_title) and due is None:
                    kind = "information_needed"
                    question = "What has your professor said about this exam or project and its timing? Tell me anything relevant; an exact date is not required to reply."
                if kind:
                    self._add(session, f"{kind}:{assignment.id}:{_signature(facts)}", kind, now,
                              assignment_id=assignment.id, facts=facts, question=question,
                              urgent=bool(due and now <= due <= now + INTERVAL), baseline=baseline)
                if baseline or not changed or effective.deadline_status != "resolved" or due is None:
                    continue
                major = bool(MAJOR.search(assignment.canonical_title)) or before is None or abs((due-before).total_seconds()) >= 21600
                if major:
                    self._add(session, f"deadline_change:{assignment.id}:{previous.id}:{_signature(facts)}", "deadline_change", now,
                              assignment_id=assignment.id, facts={**facts, "before": before.isoformat() if before else None},
                              urgent=bool(now <= due <= now + INTERVAL and (before is None or due < before)))
            if state is None:
                state = SchedulerState(key=STATE_KEY)
                session.add(state)
            state.last_successful_at = now
            session.commit()

    @staticmethod
    def _add(session, key, kind, now, *, baseline=False, **values) -> None:
        if session.scalar(select(AcademicUpdateEvent.id).where(AcademicUpdateEvent.event_key == key)) is None:
            session.add(AcademicUpdateEvent(event_key=key, kind=kind, observed_at=now,
                                          status="baseline" if baseline else "pending", **values))

    def _valid(self, session, event, *, recheck: bool) -> bool:
        if event.answered_at is not None or event.status in {"baseline", "superseded"}:
            return False
        if event.source_record_id:
            source = session.get(SourceRecord, event.source_record_id)
            if source is None or source.ingestion_status != "ingested":
                return False
            course = session.get(Course, source.course_id) if source.course_id else None
            newest = session.scalar(select(func.max(SourceRecord.id)).where(
                SourceRecord.source_system == source.source_system, SourceRecord.source_type == source.source_type,
                SourceRecord.external_id == source.external_id, SourceRecord.course_id == source.course_id,
            ))
            if course is None or not course.active or newest != source.id:
                return False
        if event.assignment_id:
            assignment = session.scalar(select(Assignment).options(*assignment_load_options()).where(Assignment.id == event.assignment_id))
            if assignment is None or not assignment.published or not assignment.course.active:
                return False
            effective = project_canvas_assignment(assignment)
            due = _utc(effective.operational_due_at).isoformat() if effective.operational_due_at else None
            if due != event.facts.get("deadline") or effective.submission_status not in INCOMPLETE:
                return False
            if event.kind == "deadline_conflict" and effective.deadline_status != "conflicted":
                return False
            if event.kind == "deadline_conflict" and sorted(event.facts.get("candidates", [])) != sorted(str(value) for value in effective.conflicting_due_at):
                return False
            if recheck:
                if self.recheck is None or self.recheck(event.assignment_id) not in INCOMPLETE:
                    return False
        return True

    def _render(self, session, events, *, followup=False) -> tuple[str, str]:
        local = _utc(self.clock()).astimezone(ZoneInfo(self.settings.timezone))
        title = "A quick follow-up from Bob" if followup else "School changes worth your attention"
        sections = ["Here's what changed—not another assignment list." if not followup else "One follow-up on the information I still need. Reply in DueSoon whenever you can."]
        if events and all(event.kind == "planning_review" for event in events):
            title = "School update preview"
            sections = ["Preview from current Canvas records, not a new professor announcement or deadline-change alert."]
        for event in events:
            if event.source_record_id:
                source = session.get(SourceRecord, event.source_record_id)
                course = session.get(Course, source.course_id)
                payload = source.raw_payload or {}
                course_name = course.name.partition("|")[2].strip() or course.name
                posted = _date(source.source_published_at, local) if source.source_published_at else "date unknown — check Canvas"
                sections.append(f"Course updates\n{_text(course_name, 45)} — {_text(str(payload.get('title') or 'Professor announcement'), 90)}\n"
                                f"Posted {posted}.\nSource excerpt (not AI analysis): {announcement_excerpt(source)}\n"
                                "Next step: review the professor's full announcement in DueSoon; interpretation is not yet verified.")
            else:
                assignment = session.scalar(select(Assignment).options(*assignment_load_options()).where(Assignment.id == event.assignment_id))
                due = datetime.fromisoformat(event.facts["deadline"]) if event.facts.get("deadline") else None
                when = _date(due, local) if due else "date unknown — check Canvas"
                if event.kind == "planning_review":
                    sections.append(f"Planning review\n{_label(assignment)}\nCurrent verified deadline: {when}.\n"
                                    "Next step: review how this fits around your work shifts. No date change is being asserted.")
                elif event.kind == "deadline_change":
                    before = datetime.fromisoformat(event.facts["before"]) if event.facts.get("before") else None
                    sections.append(f"Deadline changes\n{_label(assignment)}\nWas {_date(before, local) if before else 'date unknown'}; now {when}.\nNext step: review your plan against the updated date.")
                elif event.kind == "deadline_conflict":
                    alternatives = "; ".join(_date(datetime.fromisoformat(value), local) for value in event.facts.get("candidates", []))
                    sections.append(f"Information needed\n{_label(assignment)}\nSources disagree: {alternatives or when}.\nWhy it matters: reminders protect the earliest credible date; the final deadline still needs review.")
                else:
                    sections.append(f"Information needed\n{_label(assignment)}\n{when}.\nWhy it matters: timing is missing, so exact deadline planning is not possible.")
            if event.question:
                sections.append(event.question)
            if self.settings.public_origin:
                sections.append(f"Review or reply: {self.settings.public_origin}/app/assistant?update={event.id}")
        return title, "\n\n".join(sections)

    def _enqueue(self, events, *, followup: bool) -> int | None:
        now = _utc(self.clock())
        kind = "academic_followup" if followup else "academic_update"
        with self.sessions() as session:
            selected = []
            for item in events:
                event = session.get(AcademicUpdateEvent, item.id)
                if not self._valid(session, event, recheck=False):
                    event.status = "superseded"
                    continue
                _, candidate = self._render(session, [*selected, event], followup=followup)
                if len(_description(candidate)) > 3900:
                    break  # Remaining events stay pending for a later bundle.
                selected.append(event)
            if not selected:
                session.commit()
                return None
            title, body = self._render(session, selected, followup=followup)
            delivery = NotificationDelivery(dedup_key=f"{kind}:{_signature([event.id for event in selected])}",
                notification_kind=kind, status="retry_scheduled", rendered_title=title, rendered_body=body,
                priority=3, provider="discord", attempted_at=now)
            session.add(delivery)
            try:
                session.flush()
                ids = [event.assignment_id for event in selected if event.assignment_id]
                session.add(NotificationMirrorContext(delivery_id=delivery.id, assignment_ids=ids,
                    deadline_versions={str(event.assignment_id): event.facts["deadline"] for event in selected if event.assignment_id and event.facts.get("deadline")},
                    expires_at=now + INTERVAL, next_attempt_at=now, attempts=0))
                for event in selected:
                    if followup:
                        event.followup_delivery_id = delivery.id
                    else:
                        event.discord_delivery_id = delivery.id
                        event.status = "queued"
                session.commit()
                return delivery.id
            except IntegrityError:
                session.rollback()
                return None

    def _attempt(self, key: int) -> None:
        now = _utc(self.clock())
        with self.sessions() as session:
            context = session.get(NotificationMirrorContext, key)
            if context is None or _utc(context.next_attempt_at) > now:
                return
            claimed = session.execute(update(NotificationDelivery).where(NotificationDelivery.id == key, NotificationDelivery.status == "retry_scheduled").values(status="pending", attempted_at=now))
            if claimed.rowcount != 1:
                session.rollback()
                return
            context.attempts += 1
            session.commit()

            delivery = session.get(NotificationDelivery, key)
            followup = delivery.notification_kind == "academic_followup"
            events = list(session.scalars(select(AcademicUpdateEvent).where(
                (AcademicUpdateEvent.followup_delivery_id if followup else AcademicUpdateEvent.discord_delivery_id) == key,
            ).order_by(AcademicUpdateEvent.id)).all())
            status, error_code, provider_id = "sent", None, None
            try:
                if now >= _utc(context.expires_at):
                    status, error_code = "suppressed_stale", "update_expired"
                else:
                    valid = []
                    states = {}
                    for event in events:
                        # Fresh external submission checks precede final local
                        # version validation, so completion cannot leak into alerts.
                        if event.assignment_id and not self.settings.dry_run:
                            if self.recheck is None:
                                raise LookupError("recheck unavailable")
                            try:
                                states[str(event.assignment_id)] = self.recheck(event.assignment_id)
                            except Exception:
                                raise LookupError("submission recheck failed") from None
                            session.expire_all()
                            state = states[str(event.assignment_id)]
                            if state not in INCOMPLETE and state not in {"submitted", "graded"}:
                                raise LookupError("submission unknown")
                        if self._valid(session, event, recheck=False) and (not event.assignment_id or self.settings.dry_run or states[str(event.assignment_id)] in INCOMPLETE):
                            valid.append(event)
                    # Rechecks write through a separate session. Do not mutate
                    # events before expire_all(), which would discard those edits.
                    valid = [event for event in valid if self._valid(session, event, recheck=False)]
                    valid_ids = {event.id for event in valid}
                    for event in events:
                        if event.id not in valid_ids:
                            event.status = "superseded"
                    context.submission_rechecked_at = self.clock()
                    context.submission_recheck_statuses = states
                    if not valid:
                        status, error_code = "suppressed_stale", "update_no_longer_relevant"
                    else:
                        title, body = self._render(session, valid, followup=followup)
                        delivery.rendered_title, delivery.rendered_body = title, body
                        session.commit()
                        if self.settings.dry_run:
                            status = "dry_run"
                        elif self.publisher is None:
                            status, error_code = "failed", "provider_disabled"
                        else:
                            result = self.publisher.publish(title=title, message=body, priority=3)
                            provider_id = result.provider_message_id
                if status in {"sent", "dry_run"}:
                    for event in events:
                        if event.status == "superseded":
                            continue
                        if followup:
                            event.followed_up_at = now
                        else:
                            event.status = "preview" if delivery.notification_kind == "academic_update_preview" else "notified" if status == "sent" else "dry_run"
                            event.notified_at = now
            except (LookupError, ConnectionError):
                status, error_code = self._retry(context, "submission_recheck_failed")
            except DiscordPublishError as error:
                if error.retryable:
                    status, error_code = self._retry(context, "provider_transient", error.retry_after)
                else:
                    status, error_code = ("unknown" if error.ambiguous else "failed"), "provider_outcome"
            except Exception:
                # Never print exceptions carrying webhook URLs or course content.
                status, error_code = "unknown", "unexpected_update_outcome"
            delivery.status, delivery.error_code = status, error_code
            delivery.provider_message_id, delivery.completed_at = provider_id, self.clock()
            session.commit()

    def _retry(self, context, code, delay=None):
        wait = max(30 * 2 ** (context.attempts-1), delay or 0)
        if context.attempts >= 3 or _utc(self.clock()) + timedelta(seconds=wait) >= _utc(context.expires_at):
            return "failed", code + "_exhausted"
        context.next_attempt_at = _utc(self.clock()) + timedelta(seconds=wait)
        return "retry_scheduled", code

    def _urgent_alerts(self) -> None:
        with self.sessions() as session:
            ids = list(session.scalars(select(AcademicUpdateEvent.id).where(
                AcademicUpdateEvent.urgent.is_(True), AcademicUpdateEvent.urgent_delivery_id.is_(None),
                AcademicUpdateEvent.status.in_(("pending", "queued", "notified")),
            )).all())
        for key in ids:
            try:
                with self.sessions() as session:
                    event = session.get(AcademicUpdateEvent, key)
                    now = _utc(self.clock())
                    facts = dict(event.facts)
                    if facts.get("urgent_closed") or (facts.get("urgent_next_attempt") and now < datetime.fromisoformat(facts["urgent_next_attempt"])):
                        continue
                    due = datetime.fromisoformat(facts["deadline"]) if facts.get("deadline") else None
                    if due is None or now > due or now - _utc(event.observed_at) >= INTERVAL:
                        event.facts = {**facts, "urgent_closed": True}
                        session.commit()
                        continue
                    if not self.settings.dry_run:
                        if self.recheck is None:
                            continue
                        state = self.recheck(event.assignment_id)
                        session.expire_all()
                        if state not in INCOMPLETE:
                            continue
                    if not self._valid(session, event, recheck=False):
                        continue
                    # Existing checkpoint/adaptive notices may already cover a
                    # deadline change. Reuse their audit rather than double-ping.
                    covered = session.scalar(select(NotificationDelivery.id).join(ReminderEvent, ReminderEvent.delivery_id == NotificationDelivery.id).where(
                        ReminderEvent.assignment_id == event.assignment_id,
                        ReminderEvent.deadline_at == due,
                        NotificationDelivery.provider == "ntfy", NotificationDelivery.status == "sent",
                        NotificationDelivery.attempted_at >= _utc(event.observed_at) - timedelta(minutes=5),
                    ).order_by(NotificationDelivery.id.desc()).limit(1))
                    if covered:
                        event.urgent_delivery_id = covered
                        session.commit()
                        continue
                    _, body = self._render(session, [event])
                    dedup_key = f"academic-update-urgent:{event.event_key}"
                    attempts = facts.get("urgent_attempts", 0) + 1
                    event.facts = {**facts, "urgent_attempts": attempts, "urgent_next_attempt": (now + timedelta(minutes=5)).isoformat()}
                    session.commit()
                    try:
                        result = self.notifications.send_reminder(idempotency_key=dedup_key,
                            title="DueSoon: important school change", message=body[:1000], priority=4,
                            notification_kind="academic_update_urgent")
                        event.urgent_delivery_id = result.delivery_id
                    except Exception:
                        delivery = session.scalar(select(NotificationDelivery).where(NotificationDelivery.dedup_key == dedup_key))
                        if delivery and (delivery.status != "retry_scheduled" or attempts >= 3):
                            if delivery.status == "retry_scheduled":
                                delivery.status, delivery.error_code = "failed", "urgent_retries_exhausted"
                            event.urgent_delivery_id = delivery.id
                    session.commit()
            except Exception:
                logger.warning("Academic update ntfy delivery deferred; standard reminders continue")

    def inspect(self, event_id: int) -> dict:
        with self.sessions() as session:
            event = session.get(AcademicUpdateEvent, event_id)
            if event is None:
                raise LookupError("Academic update not found")
            title, body = self._render(session, [event])
            return {"id": event.id, "kind": event.kind, "status": event.status, "title": title,
                    "body": body, "question": event.question, "answered": event.answered_at is not None,
                    "source_record_id": event.source_record_id, "assignment_id": event.assignment_id}

    def remember_reply(self, event_id: int, response: str) -> dict:
        with self.sessions() as session:
            event = session.get(AcademicUpdateEvent, event_id)
            if event is None:
                raise LookupError("Academic update not found")
            note = AcademicNote(public_id=str(uuid4()), title=f"Reply to Bob: {event.kind.replace('_', ' ')}",
                body=response, assignment_id=event.assignment_id,
                course_id=session.get(SourceRecord, event.source_record_id).course_id if event.source_record_id else None)
            session.add(note)
            session.flush()
            event.reply_note_id, event.answered_at = note.id, self.clock()
            session.commit()
        # An answer records owner context only; it is not a deadline confirmation.
        return self.inspect(event_id)
