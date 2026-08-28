"""Canvas-backed checkpoint reminder orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.models import (
    Assignment,
    ReminderEvent,
    SchedulerState,
)
from src.duesoon.reminders.checkpoints import crossed_checkpoint


COMPLETED_STATUSES = {"submitted", "graded"}
SCHEDULER_STATE_KEY = "canvas_reminders"


@dataclass(frozen=True)
class ReminderRunSummary:
    sent: int = 0
    suppressed: int = 0
    dry_run: int = 0


class ReminderService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        canvas_sync: CanvasSyncService,
        notifications: NotificationService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._canvas_sync = canvas_sync
        self._notifications = notifications
        self._clock = clock

    def run_once(self) -> ReminderRunSummary:
        self._canvas_sync.sync()
        now = _as_utc(self._clock())
        previous = self._last_successful_evaluation()
        candidates = self._candidate_assignments()
        sent = suppressed = dry_run = 0

        for assignment in candidates:
            deadline = assignment.canvas_due_at
            if deadline is None:
                continue
            checkpoint = crossed_checkpoint(deadline, previous, now)
            if checkpoint is None:
                continue

            event = self._claim_event(assignment.id, deadline, checkpoint, now)
            if event is None:
                continue

            refreshed_status = self._canvas_sync.refresh_submission(assignment.id)
            self._record_recheck(event.id, refreshed_status, now)
            if refreshed_status in COMPLETED_STATUSES:
                self._finish_event(
                    event.id,
                    status="suppressed_submission",
                    reason=f"Canvas submission status is {refreshed_status}",
                )
                suppressed += 1
                continue

            result = self._notifications.send_reminder(
                idempotency_key=_dedup_key(assignment.id, deadline, checkpoint),
                title=_title(assignment.course.name),
                message=_message(assignment, deadline, checkpoint, now),
                priority=_priority(checkpoint),
            )
            final_status = (
                "sent"
                if result.status in {"sent", "already_sent"}
                else result.status
            )
            self._finish_event(
                event.id,
                status=final_status,
                reason=f"Crossed {checkpoint}-minute checkpoint",
                delivery_id=result.delivery_id,
            )
            if final_status == "sent":
                sent += 1
            elif final_status == "dry_run":
                dry_run += 1

        self._advance_watermark(now)
        return ReminderRunSummary(sent=sent, suppressed=suppressed, dry_run=dry_run)

    def _last_successful_evaluation(self) -> datetime | None:
        with self._sessions() as session:
            state = session.get(SchedulerState, SCHEDULER_STATE_KEY)
            return state.last_successful_at if state is not None else None

    def _candidate_assignments(self) -> list[Assignment]:
        with self._sessions() as session:
            assignments = session.scalars(
                select(Assignment)
                .options(
                    selectinload(Assignment.course),
                    selectinload(Assignment.submission),
                )
                .where(
                    Assignment.canvas_due_at.is_not(None),
                    Assignment.published.is_(True),
                )
                .order_by(Assignment.canvas_due_at, Assignment.id)
            ).all()
            return [
                assignment
                for assignment in assignments
                if assignment.submission is None
                or assignment.submission.normalized_status not in COMPLETED_STATUSES
            ]

    def _claim_event(
        self,
        assignment_id: int,
        deadline: datetime,
        checkpoint: int,
        now: datetime,
    ) -> ReminderEvent | None:
        with self._sessions() as session:
            existing = session.scalar(
                select(ReminderEvent).where(
                    ReminderEvent.assignment_id == assignment_id,
                    ReminderEvent.deadline_at == deadline,
                    ReminderEvent.checkpoint_minutes == checkpoint,
                )
            )
            if existing is not None:
                if existing.status in {
                    "sent",
                    "dry_run",
                    "suppressed_submission",
                    "suppressed_catchup",
                }:
                    return None
                return existing

            event = ReminderEvent(
                assignment_id=assignment_id,
                deadline_at=deadline,
                checkpoint_minutes=checkpoint,
                status="claimed",
                reason=f"Crossed {checkpoint}-minute checkpoint",
                evaluated_at=now,
            )
            session.add(event)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return None
            return event

    def _record_recheck(self, event_id: int, status: str, checked_at: datetime) -> None:
        with self._sessions() as session:
            event = session.get(ReminderEvent, event_id)
            if event is None:
                raise LookupError("reminder event not found")
            event.submission_recheck_status = status
            event.submission_rechecked_at = checked_at
            session.commit()

    def _finish_event(
        self,
        event_id: int,
        *,
        status: str,
        reason: str,
        delivery_id: int | None = None,
    ) -> None:
        with self._sessions() as session:
            event = session.get(ReminderEvent, event_id)
            if event is None:
                raise LookupError("reminder event not found")
            event.status = status
            event.reason = reason
            event.delivery_id = delivery_id
            session.commit()

    def _advance_watermark(self, now: datetime) -> None:
        with self._sessions() as session:
            state = session.get(SchedulerState, SCHEDULER_STATE_KEY)
            if state is None:
                state = SchedulerState(key=SCHEDULER_STATE_KEY)
                session.add(state)
            state.last_successful_at = now
            session.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dedup_key(assignment_id: int, deadline: datetime, checkpoint: int) -> str:
    return f"checkpoint:{assignment_id}:{_as_utc(deadline).isoformat()}:{checkpoint}"


def _title(course_name: str) -> str:
    return f"DueSoon - {course_name}"[:200]


def _message(
    assignment: Assignment,
    deadline: datetime,
    checkpoint: int,
    now: datetime,
) -> str:
    remaining = _as_utc(deadline) - now
    total_minutes = max(0, int(remaining.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    due_text = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    message = (
        f"{assignment.canonical_title}\n"
        f"Due in {due_text}. {checkpoint}-minute checkpoint.\n"
        f"{assignment.html_url or ''}"
    )
    return message[:1000]


def _priority(checkpoint: int) -> int:
    if checkpoint <= 60:
        return 5
    if checkpoint <= 360:
        return 4
    return 3
