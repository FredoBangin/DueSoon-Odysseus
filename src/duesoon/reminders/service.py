"""Canvas-backed checkpoint reminder orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.assignments.effective import (
    EffectiveAssignment,
    project_canvas_assignment,
)
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    NotificationDelivery,
    ReminderEvent,
    SchedulerState,
)
from src.duesoon.planning import PlanningService
from src.duesoon.reminders.checkpoints import adaptive_interval_key, crossed_checkpoint


COMPLETED_STATUSES = {"submitted", "graded"}
SCHEDULER_STATE_KEY = "canvas_reminders"
RECONCILABLE_EVENT_STATUSES = {"pending", "claimed", "retry_scheduled"}


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
        settings: DueSoonSettings | None = None,
        planning: PlanningService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        assignment_projector: Callable[[Assignment], EffectiveAssignment] = (
            project_canvas_assignment
        ),
    ) -> None:
        self._sessions = sessions
        self._canvas_sync = canvas_sync
        self._notifications = notifications
        self._settings = settings
        self._planning = planning
        self._clock = clock
        self._assignment_projector = assignment_projector

    def run_once(self) -> ReminderRunSummary:
        self._canvas_sync.sync()
        now = _as_utc(self._clock())
        previous = self._last_successful_evaluation()
        assignments = self._assignments()
        sent = suppressed = dry_run = 0

        for assignment, effective in assignments:
            deadline = effective.operational_due_at
            self._reconcile_deadline_version(assignment.id, deadline)
            if (
                deadline is None
                or not assignment.published
                or effective.submission_status in COMPLETED_STATUSES
                or effective.deadline_confidence == "low"
            ):
                continue
            evaluation_start = previous
            changed_earlier = _changed_earlier_since_last_evaluation(effective, previous)
            if changed_earlier:
                # A newly earlier deadline may have moved every checkpoint before
                # the global watermark. Treat it like an initial observation so
                # reconciliation can select one safe, current checkpoint now.
                evaluation_start = None
            checkpoint = crossed_checkpoint(deadline, evaluation_start, now)
            if checkpoint is None:
                continue

            interval_key = None
            reminder_kind = "standard"
            if (
                changed_earlier
                and (effective.deadline_change_hours or 0) >= 6
            ):
                interval_key = adaptive_interval_key(deadline - now)
                if interval_key is not None:
                    reminder_kind = "adaptive"

            event = self._claim_event(
                assignment.id,
                deadline,
                checkpoint,
                now,
                reminder_kind=reminder_kind,
                interval_key=interval_key,
            )
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
                idempotency_key=_dedup_key(
                    assignment.id,
                    deadline,
                    checkpoint,
                    reminder_kind=reminder_kind,
                    interval_key=interval_key,
                ),
                title=_title(assignment.course.name),
                message=_message(
                    assignment,
                    deadline,
                    checkpoint,
                    now,
                    earlier_move_hours=(
                        effective.deadline_change_hours
                        if reminder_kind == "adaptive"
                        else None
                    ),
                ),
                priority=_priority(checkpoint),
                notification_kind=(
                    "adaptive_deadline_change"
                    if reminder_kind == "adaptive"
                    else "deadline_checkpoint"
                ),
            )
            final_status = (
                "sent"
                if result.status in {"sent", "already_sent"}
                else result.status
            )
            self._finish_event(
                event.id,
                status=final_status,
                reason=(
                    f"Adaptive deadline change in interval {interval_key}"
                    if reminder_kind == "adaptive"
                    else f"Crossed {checkpoint}-minute checkpoint"
                ),
                delivery_id=result.delivery_id,
            )
            if final_status == "sent":
                sent += 1
            elif final_status == "dry_run":
                dry_run += 1

        digest_status = self._send_daily_digest(assignments, now)
        if digest_status == "sent":
            sent += 1
        elif digest_status == "dry_run":
            dry_run += 1

        self._advance_watermark(now)
        return ReminderRunSummary(sent=sent, suppressed=suppressed, dry_run=dry_run)

    def _send_daily_digest(
        self,
        assignments: list[tuple[Assignment, EffectiveAssignment]],
        now: datetime,
    ) -> str | None:
        settings = self._settings
        if settings is None or not settings.daily_digest_enabled:
            return None
        try:
            local_now = now.astimezone(ZoneInfo(settings.timezone))
        except ZoneInfoNotFoundError:
            local_now = now
        if local_now.hour < settings.daily_digest_hour:
            return None
        local_day = local_now.date().isoformat()
        dedup_key = f"daily-digest:{local_day}"
        with self._sessions() as session:
            existing = session.scalar(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.dedup_key == dedup_key
                )
            )
        if existing is not None:
            return None

        eligible = [
            (assignment, effective)
            for assignment, effective in assignments
            if assignment.published
            and effective.operational_due_at is not None
            and effective.deadline_confidence != "low"
            and effective.submission_status not in COMPLETED_STATUSES
        ]
        if not eligible:
            return None
        if self._planning is not None:
            projected = tuple(effective for _, effective in eligible)
            priorities = self._planning.priorities(projected, now)
            eligible.sort(
                key=lambda value: (
                    -priorities[value[0].id].total,
                    _as_utc(value[1].operational_due_at),
                    value[0].id,
                )
            )
        else:
            eligible.sort(
                key=lambda value: (_as_utc(value[1].operational_due_at), value[0].id)
            )
        eligible = eligible[: settings.daily_digest_max_items]

        active: list[tuple[Assignment, EffectiveAssignment]] = []
        for assignment, effective in eligible:
            status = self._canvas_sync.refresh_submission(assignment.id)
            if status not in COMPLETED_STATUSES:
                active.append((assignment, effective))
        if not active:
            return None

        lines = []
        for assignment, effective in active:
            due = _as_utc(effective.operational_due_at).astimezone(local_now.tzinfo)
            lines.append(
                f"{assignment.course.name}: {assignment.canonical_title} · due {due.strftime('%a %I:%M %p').lstrip('0')}"
            )
        result = self._notifications.send_reminder(
            idempotency_key=dedup_key,
            title="DueSoon daily briefing",
            message="\n".join(lines)[:1000],
            priority=3,
            notification_kind="daily_digest",
        )
        return "sent" if result.status in {"sent", "already_sent"} else result.status

    def _last_successful_evaluation(self) -> datetime | None:
        with self._sessions() as session:
            state = session.get(SchedulerState, SCHEDULER_STATE_KEY)
            return state.last_successful_at if state is not None else None

    def _assignments(self) -> list[tuple[Assignment, EffectiveAssignment]]:
        with self._sessions() as session:
            assignments = session.scalars(
                select(Assignment)
                .options(
                    selectinload(Assignment.course),
                    selectinload(Assignment.submission),
                    selectinload(Assignment.snapshots),
                    selectinload(Assignment.evidence)
                    .selectinload(AssignmentEvidence.claim)
                    .selectinload(Claim.source_record),
                )
                .order_by(Assignment.id)
            ).all()
            return [
                (assignment, self._assignment_projector(assignment))
                for assignment in assignments
            ]

    def _reconcile_deadline_version(
        self,
        assignment_id: int,
        operational_due_at: datetime | None,
    ) -> None:
        """Cancel only unsent events belonging to obsolete deadline versions."""

        current = _as_utc(operational_due_at) if operational_due_at is not None else None
        with self._sessions() as session:
            events = session.scalars(
                select(ReminderEvent).where(
                    ReminderEvent.assignment_id == assignment_id,
                    ReminderEvent.status.in_(RECONCILABLE_EVENT_STATUSES),
                )
            ).all()
            changed = False
            for event in events:
                if current is not None and _as_utc(event.deadline_at) == current:
                    continue
                event.status = "cancelled_deadline_change"
                event.reason = (
                    "Operational deadline was removed"
                    if current is None
                    else "Operational deadline changed; reminder version replaced"
                )
                changed = True
            if changed:
                session.commit()

    def _claim_event(
        self,
        assignment_id: int,
        deadline: datetime,
        checkpoint: int,
        now: datetime,
        *,
        reminder_kind: str = "standard",
        interval_key: str | None = None,
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
                reminder_kind=reminder_kind,
                interval_key=interval_key,
                status="claimed",
                reason=(
                    f"Adaptive deadline change in interval {interval_key}"
                    if reminder_kind == "adaptive"
                    else f"Crossed {checkpoint}-minute checkpoint"
                ),
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


def _dedup_key(
    assignment_id: int,
    deadline: datetime,
    checkpoint: int,
    *,
    reminder_kind: str = "standard",
    interval_key: str | None = None,
) -> str:
    version = _as_utc(deadline).isoformat()
    if reminder_kind == "adaptive":
        return f"adaptive:{assignment_id}:{version}:{interval_key}"
    return f"checkpoint:{assignment_id}:{version}:{checkpoint}"


def _title(course_name: str) -> str:
    return f"DueSoon - {course_name}"[:200]


def _message(
    assignment: Assignment,
    deadline: datetime,
    checkpoint: int,
    now: datetime,
    earlier_move_hours: float | None = None,
) -> str:
    remaining = _as_utc(deadline) - now
    total_minutes = max(0, int(remaining.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    due_text = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    change_text = (
        f"Deadline moved {earlier_move_hours:g} hours earlier. "
        if earlier_move_hours is not None
        else ""
    )
    message = (
        f"{assignment.canonical_title}\n"
        f"{change_text}Due in {due_text}. {checkpoint}-minute checkpoint.\n"
        f"{assignment.html_url or ''}"
    )
    return message[:1000]


def _priority(checkpoint: int) -> int:
    if checkpoint <= 60:
        return 5
    if checkpoint <= 360:
        return 4
    return 3


def _changed_earlier_since_last_evaluation(
    assignment: EffectiveAssignment,
    previous_evaluated_at: datetime | None,
) -> bool:
    previous_due = assignment.previous_due_at
    current_due = assignment.operational_due_at
    changed_at = assignment.deadline_changed_at
    if previous_due is None or current_due is None or changed_at is None:
        return False
    if _as_utc(current_due) >= _as_utc(previous_due):
        return False
    return (
        previous_evaluated_at is None
        or _as_utc(changed_at) > _as_utc(previous_evaluated_at)
    )
