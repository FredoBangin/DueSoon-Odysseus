"""Privacy-safe aggregate diagnostics for calibration and operations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.intelligence.service import assignment_load_options
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    NotificationDelivery,
    ReminderEvent,
    SchedulerState,
    SourceRecord,
    SyncRun,
)
from src.duesoon.reminders.service import SCHEDULER_STATE_KEY
from src.duesoon.urgency.scoring import score_assignment


COMPLETE = frozenset({"submitted", "graded", "cancelled"})
BANDS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _age(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, int((now - _utc(value)).total_seconds()))


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


class DiagnosticsService:
    """Return counts and timing only; never titles, messages, excerpts, or identities."""

    def __init__(
        self,
        settings: DueSoonSettings,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.clock = clock

    def snapshot(self) -> dict[str, Any]:
        now = _utc(self.clock())
        with self.sessions() as session:
            records = session.scalars(
                select(Assignment)
                .options(*assignment_load_options())
                .where(Assignment.published.is_(True))
                .order_by(Assignment.id)
            ).all()
            projected = tuple(project_canvas_assignment(item) for item in records)
            active_pairs = [
                (record, item)
                for record, item in zip(records, projected, strict=True)
                if item.submission_status.casefold() not in COMPLETE
            ]
            scores = [
                (record, item, score_assignment(item, projected, now))
                for record, item in active_pairs
            ]
            bands = Counter(score.level for _record, _item, score in scores)
            missing = Counter()
            for record, item, score in scores:
                if score.level != "LOW":
                    continue
                if item.operational_due_at is None:
                    missing["no_operational_deadline"] += 1
                if item.points_possible is None:
                    missing["no_points_possible"] += 1
                if item.persisted_deadline_evidence_count == 0:
                    missing["no_persisted_deadline_evidence"] += 1
                if record.submission is None:
                    missing["no_submission_observation"] += 1

            claims_by_status = _counts(session.scalars(select(Claim.validation_status)).all())
            links_by_disposition = _counts(
                session.scalars(select(AssignmentEvidence.disposition)).all()
            )
            sources_by_status = _counts(
                session.scalars(select(SourceRecord.ingestion_status)).all()
            )
            unresolved = session.scalars(
                select(Claim.id).where(
                    or_(
                        Claim.validation_status != "validated",
                        ~Claim.assignment_links.any(),
                        Claim.assignment_links.any(
                            AssignmentEvidence.disposition != "admitted"
                        ),
                    )
                )
            ).all()
            latest_sync = session.scalar(
                select(SyncRun)
                .where(SyncRun.status.in_(("completed", "success")))
                .order_by(SyncRun.finished_at.desc(), SyncRun.id.desc())
            )
            scheduler = session.get(SchedulerState, SCHEDULER_STATE_KEY)
            reminder_counts = _counts(
                session.scalars(select(ReminderEvent.status)).all()
            )
            delivery_counts = _counts(
                session.scalars(select(NotificationDelivery.status)).all()
            )

        sync_at = latest_sync.finished_at if latest_sync else None
        watermark = scheduler.last_successful_at if scheduler else None
        scheduler_lag = _age(now, watermark)
        evidence_assignments = sum(
            item.persisted_deadline_evidence_count > 0 for item in projected
        )
        total = len(projected)
        return {
            "generated_at": now.isoformat(),
            "privacy": "aggregate_only_no_academic_content",
            "assignments": {
                "published": total,
                "active": len(active_pairs),
                "completed": total - len(active_pairs),
                "without_operational_deadline": sum(
                    item.operational_due_at is None for item in projected
                ),
                "deadline_conflicts": sum(
                    item.deadline_status == "conflicted" for item in projected
                ),
            },
            "urgency": {
                "bands": {band: bands.get(band, 0) for band in BANDS},
                "score_buckets": {
                    "0_24": sum(score.total < 25 for _r, _i, score in scores),
                    "25_49": sum(25 <= score.total < 50 for _r, _i, score in scores),
                    "50_74": sum(50 <= score.total < 75 for _r, _i, score in scores),
                    "75_100": sum(score.total >= 75 for _r, _i, score in scores),
                },
                "low_missing_factors": {
                    name: missing.get(name, 0)
                    for name in (
                        "no_operational_deadline",
                        "no_points_possible",
                        "no_persisted_deadline_evidence",
                        "no_submission_observation",
                    )
                },
            },
            "evidence": {
                "assignments_with_deadline_evidence": evidence_assignments,
                "assignment_coverage_percent": round(
                    100 * evidence_assignments / total, 1
                ) if total else 0.0,
                "unresolved_claims": len(unresolved),
                "claims_by_status": claims_by_status,
                "links_by_disposition": links_by_disposition,
                "sources_by_ingestion_status": sources_by_status,
            },
            "operations": {
                "last_canvas_sync_at": _utc(sync_at).isoformat() if sync_at else None,
                "canvas_sync_age_seconds": _age(now, sync_at),
                "scheduler_watermark_at": (
                    _utc(watermark).isoformat() if watermark else None
                ),
                "scheduler_lag_seconds": scheduler_lag,
                "scheduler_lag_intervals": (
                    round(scheduler_lag / self.settings.scheduler_interval_seconds, 2)
                    if scheduler_lag is not None else None
                ),
                "reminder_events_by_status": reminder_counts,
                "deliveries_by_status": delivery_counts,
            },
        }
