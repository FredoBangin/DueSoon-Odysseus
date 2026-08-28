"""Browser-safe academic briefing and calendar projections."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.assignments.effective import EffectiveAssignment, project_canvas_assignment
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    NotificationDelivery,
    ReminderEvent,
    SyncRun,
)
from src.duesoon.urgency.scoring import score_assignment

COLORS = ("#0b84f3", "#8b5cf6", "#e4553d", "#1b9e77", "#d97706", "#db2777")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _color(course_id: str) -> str:
    return COLORS[int(hashlib.sha256(course_id.encode()).hexdigest()[:8], 16) % len(COLORS)]


class BriefingService:
    def __init__(self, settings: DueSoonSettings, sessions: sessionmaker[Session]) -> None:
        self.settings, self.sessions = settings, sessions

    def _items(self) -> tuple[EffectiveAssignment, ...]:
        with self.sessions() as session:
            records = session.scalars(select(Assignment).options(
                selectinload(Assignment.course),
                selectinload(Assignment.submission),
                selectinload(Assignment.snapshots),
                selectinload(Assignment.evidence)
                .selectinload(AssignmentEvidence.claim)
                .selectinload(Claim.source_record),
            ).where(Assignment.published.is_(True))).all()
            return tuple(project_canvas_assignment(record) for record in records)

    def _view(self, item: EffectiveAssignment, items: tuple[EffectiveAssignment, ...], now: datetime) -> dict[str, object]:
        urgency = score_assignment(item, items, now)
        return {
            "id": item.assignment_id, "title": item.title, "course_name": item.course_name,
            "due_at": _utc(item.operational_due_at).isoformat() if item.operational_due_at else None,
            "effective_due_at": _utc(item.effective_due_at).isoformat() if item.effective_due_at else None,
            "submission_status": item.submission_status, "points_possible": item.points_possible,
            "external_url": item.external_url, "deadline_status": item.deadline_status,
            "deadline_confidence": item.deadline_confidence,
            "deadline_source_summary": item.deadline_source_summary,
            "deadline_evidence_ids": list(item.deadline_evidence_ids),
            "due_at_precision": item.due_at_precision,
            "deadline_resolution_explanation": item.deadline_resolution_explanation,
            "conflicting_due_at": [
                _utc(value).isoformat() for value in item.conflicting_due_at
            ],
            "urgency": urgency.to_dict(), "course_color": _color(item.canvas_course_id),
        }

    def _deadline_change_view(self, item: EffectiveAssignment) -> dict[str, object] | None:
        previous = item.previous_due_at
        current = item.effective_due_at
        changed_at = item.deadline_changed_at
        if previous is None or changed_at is None:
            return None
        previous_utc = _utc(previous)
        current_utc = _utc(current) if current is not None else None
        if current_utc == previous_utc:
            return None
        direction = (
            "removed"
            if current_utc is None
            else "earlier"
            if current_utc < previous_utc
            else "later"
        )
        return {
            "assignment_id": item.assignment_id,
            "title": item.title,
            "course_name": item.course_name,
            "previous_due_at": previous_utc.isoformat(),
            "effective_due_at": current_utc.isoformat() if current_utc else None,
            "changed_at": _utc(changed_at).isoformat(),
            "direction": direction,
            "difference_hours": item.deadline_change_hours,
            "deadline_status": item.deadline_status,
            "deadline_confidence": item.deadline_confidence,
            "deadline_evidence_ids": list(item.deadline_evidence_ids),
            "due_at_precision": item.due_at_precision,
            "resolution_explanation": item.deadline_resolution_explanation,
            "conflicting_due_at": [
                _utc(value).isoformat() for value in item.conflicting_due_at
            ],
        }

    def snapshot(self, now: datetime | None = None) -> dict[str, object]:
        now = _utc(now or datetime.now(UTC))
        items = self._items()
        views = [self._view(item, items, now) for item in items]
        incomplete = [v for v in views if v["submission_status"] not in {"submitted", "graded"}]
        due_items = [v for v in incomplete if v["due_at"]]
        due_items.sort(key=lambda value: str(value["due_at"]))
        urgent = [v for v in due_items if v["urgency"]["level"] in {"HIGH", "CRITICAL"}]
        overdue = [v for v in due_items if datetime.fromisoformat(str(v["due_at"])) < now]
        missing = [v for v in incomplete if v["submission_status"] == "missing"]
        completed = [v for v in views if v["submission_status"] in {"submitted", "graded"}]
        deadline_changes = [
            change
            for item in items
            if (change := self._deadline_change_view(item)) is not None
        ]
        deadline_changes.sort(key=lambda value: str(value["changed_at"]), reverse=True)
        has_persisted_deadline_evidence = any(
            item.persisted_deadline_evidence_count > 0 for item in items
        )
        with self.sessions() as session:
            latest_sync = session.scalar(
                select(SyncRun)
                .where(SyncRun.status.in_(("completed", "success")))
                .order_by(SyncRun.finished_at.desc())
            )
            reminder_counts = dict(Counter(session.scalars(select(ReminderEvent.status)).all()))
        synced_at = _utc(latest_sync.finished_at).isoformat() if latest_sync and latest_sync.finished_at else None
        stale = not synced_at or now - datetime.fromisoformat(synced_at) > timedelta(seconds=self.settings.scheduler_interval_seconds * 2)
        return {
            "generated_at": now.isoformat(), "timezone": self.settings.timezone,
            "urgent": urgent, "upcoming": due_items[:10], "overdue": overdue,
            "missing": missing, "completed_recently": completed[:10],
            "deadline_changes": deadline_changes[:10],
            "reminder_counts": reminder_counts,
            "freshness": {"canvas_status": "stale" if stale else "fresh", "last_synced_at": synced_at},
            "questions": [],
            "limitations": (
                []
                if has_persisted_deadline_evidence
                else ["Deadline evidence is currently Canvas-only"]
            ),
        }

    def calendar(self, start: date, end: date, now: datetime | None = None) -> dict[str, object]:
        if end < start or (end - start).days > 93:
            raise ValueError("calendar range must be ordered and at most 93 days")
        now = _utc(now or datetime.now(UTC))
        try:
            tz = ZoneInfo(self.settings.timezone)
        except ZoneInfoNotFoundError:
            # Windows development hosts may lack the optional tzdata wheel;
            # production Linux uses the system IANA database.
            tz = datetime.now().astimezone().tzinfo or UTC
        items = self._items(); events = []
        for item in items:
            if not item.operational_due_at: continue
            due = _utc(item.operational_due_at); local = due.astimezone(tz)
            if not start <= local.date() <= end: continue
            urgency = score_assignment(item, items, now)
            status = item.submission_status if item.submission_status in {"missing", "submitted", "graded"} else "overdue" if due < now else "upcoming"
            events.append({"id": f"canvas-{item.assignment_id}", "assignment_id": item.assignment_id,
                           "title": item.title, "course_name": item.course_name,
                           "starts_at": due.isoformat(), "local_date": local.date().isoformat(),
                           "local_time": local.strftime("%I:%M %p").lstrip("0"),
                           "color": _color(item.canvas_course_id), "status": status,
                           "urgency_level": urgency.level, "source": "canvas", "read_only": True,
                           "external_url": item.external_url})
        events.sort(key=lambda event: str(event["starts_at"]))
        return {"start": start.isoformat(), "end": end.isoformat(), "timezone": self.settings.timezone, "events": events}

    def notifications(self, limit: int) -> dict[str, object]:
        with self.sessions() as session:
            rows = session.scalars(select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc()).limit(limit)).all()
            return {"items": [{"id": row.id, "kind": row.notification_kind, "status": row.status,
                               "title": row.rendered_title, "body": row.rendered_body,
                               "priority": row.priority, "provider": row.provider,
                               "attempted_at": _utc(row.attempted_at).isoformat(),
                               "completed_at": _utc(row.completed_at).isoformat() if row.completed_at else None,
                               "error_code": row.error_code} for row in rows]}
