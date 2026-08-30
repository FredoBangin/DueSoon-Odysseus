"""Pure work-priority scoring kept separate from reminder urgency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import sqrt
from typing import Any, Sequence

from src.duesoon.assignments.effective import EffectiveAssignment


POLICY_VERSION = "work-priority-v2"
COMPLETE = frozenset({"submitted", "graded", "cancelled"})


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class EffortProjection:
    estimated_minutes: int | None
    lower_minutes: int | None
    upper_minutes: int | None
    remaining_minutes: int | None
    progress_percent: int | None
    confidence: str
    source: str
    evidence_ids: tuple[str, ...]
    assumptions: tuple[str, ...]

    @classmethod
    def unknown(cls) -> "EffortProjection":
        return cls(
            estimated_minutes=None,
            lower_minutes=None,
            upper_minutes=None,
            remaining_minutes=None,
            progress_percent=None,
            confidence="low",
            source="unknown",
            evidence_ids=(),
            assumptions=("Effort is unknown; no exact estimate was invented.",),
        )


@dataclass(frozen=True)
class WorkPriorityBreakdown:
    workload_pressure_score: int
    due_proximity_score: int
    course_value_score: int
    overlap_score: int
    instructor_signal_score: int
    total: int
    band: str
    start_by_at: datetime | None
    slack_minutes: int | None
    usable_minutes_until_due: int | None
    calendar_blocked_minutes: int
    estimated_effort_minutes: int | None
    remaining_effort_minutes: int | None
    progress_percent: int | None
    effort_confidence: str
    confidence: str
    effort_source: str
    evidence_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    reasons: tuple[str, ...]
    config_version: str = POLICY_VERSION

    @property
    def factor_breakdown(self) -> dict[str, int]:
        return {
            "workload_pressure": self.workload_pressure_score,
            "due_proximity": self.due_proximity_score,
            "course_value": self.course_value_score,
            "overlap": self.overlap_score,
            "instructor_signal": self.instructor_signal_score,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.total,
            "band": self.band,
            "start_by_at": self.start_by_at.isoformat() if self.start_by_at else None,
            "slack_minutes": self.slack_minutes,
            "usable_minutes_until_due": self.usable_minutes_until_due,
            "calendar_blocked_minutes": self.calendar_blocked_minutes,
            "estimated_effort_minutes": self.estimated_effort_minutes,
            "remaining_effort_minutes": self.remaining_effort_minutes,
            "progress_percent": self.progress_percent,
            "effort_confidence": self.effort_confidence,
            "confidence": self.confidence,
            "effort_source": self.effort_source,
            "factor_breakdown": self.factor_breakdown,
            "reasons": list(self.reasons),
            "assumptions": list(self.assumptions),
            "evidence_ids": list(self.evidence_ids),
            "config_version": self.config_version,
        }


def score_work_priority(
    item: EffectiveAssignment,
    all_items: Sequence[EffectiveAssignment],
    effort: EffortProjection,
    now: datetime,
    *,
    course_value_percentile: float | None = None,
    usable_hours_per_day: float | None = None,
    calendar_blocked_minutes: int = 0,
) -> WorkPriorityBreakdown:
    """Calculate what should start now; never modifies urgency or reminders."""

    if item.submission_status.casefold() in COMPLETE:
        return WorkPriorityBreakdown(
            0, 0, 0, 0, 0, 0, "MONITOR", None, None, None, 0,
            effort.estimated_minutes, 0, effort.progress_percent,
            effort.confidence, "high", effort.source, effort.evidence_ids,
            effort.assumptions, ("Work is complete",),
        )

    now = _utc(now)
    due = _utc(item.operational_due_at) if item.operational_due_at else None
    remaining = effort.remaining_minutes
    assumptions = [*effort.assumptions]
    reasons: list[str] = []
    pressure_score = due_score = value_score = overlap_score = instructor_score = 0
    start_by = None
    slack = usable = None
    blocked = max(0, calendar_blocked_minutes)

    if remaining is None:
        reasons.append("Effort is unknown")
    if due is None:
        reasons.append("No operational deadline is precise enough for start-by planning")
    elif remaining is not None:
        wall_minutes = max(0, round((due - now).total_seconds() / 60))
        blocked = min(blocked, wall_minutes)
        if blocked:
            reasons.append(
                f"Known calendar commitments block {blocked} minute(s) before the deadline"
            )
        buffer = max(30, round(remaining * 0.20))
        required = remaining + buffer
        if usable_hours_per_day is None:
            pressure_score = min(60, round(60 * sqrt(required / max(wall_minutes, 1))))
            assumptions.append(
                "Work capacity is unknown; start-by time and exact slack were not invented."
            )
            reasons.append(
                f"{remaining} estimated work minutes plus {buffer} buffer are spread across the remaining calendar time"
            )
        else:
            unblocked_wall_minutes = max(0, wall_minutes - blocked)
            usable = round(unblocked_wall_minutes * usable_hours_per_day / 24)
            slack = usable - required
            pressure_score = min(60, round(60 * sqrt(max(0.0, required / max(usable, 1)))))
            wall_required = round(required * 24 / usable_hours_per_day)
            start_by = due - timedelta(minutes=wall_required)
            assumptions.append(
                f"Learned outcome history supplies {usable_hours_per_day:g} usable school-work hours per day; known calendar blocks remain separate context."
            )
            reasons.append(
                f"{remaining} estimated work minutes plus {buffer} buffer leave {slack} usable minutes of slack"
            )

    if due is not None:
        hours = max(0.0, (due - now).total_seconds() / 3600)
        due_score = round(15 * max(0.0, 1 - min(hours, 168) / 168))
    if course_value_percentile is not None:
        value_score = max(0, min(10, round(10 * course_value_percentile)))
    if due is not None:
        overlap = sum(
            other.assignment_id != item.assignment_id
            and other.submission_status.casefold() not in COMPLETE
            and other.operational_due_at is not None
            and abs((_utc(other.operational_due_at) - due).total_seconds()) <= 48 * 3600
            for other in all_items
        )
        overlap_score = min(10, overlap * 2)
        if overlap:
            reasons.append(f"{overlap} other active item(s) have deadlines within 48 hours")
    if effort.source == "validated_workload_evidence":
        instructor_score = 5
        reasons.append("Validated instructor workload evidence supports the estimate")

    total = min(100, pressure_score + due_score + value_score + overlap_score + instructor_score)
    if remaining is None or due is None:
        band = "MONITOR"
    elif total >= 70:
        band = "NOW"
    elif total >= 45:
        band = "NEXT"
    elif total >= 20:
        band = "LATER"
    else:
        band = "MONITOR"
    confidence = "medium" if usable_hours_per_day is not None else "low"
    return WorkPriorityBreakdown(
        workload_pressure_score=pressure_score,
        due_proximity_score=due_score,
        course_value_score=value_score,
        overlap_score=overlap_score,
        instructor_signal_score=instructor_score,
        total=total,
        band=band,
        start_by_at=start_by,
        slack_minutes=slack,
        usable_minutes_until_due=usable,
        calendar_blocked_minutes=blocked,
        estimated_effort_minutes=effort.estimated_minutes,
        remaining_effort_minutes=remaining,
        progress_percent=effort.progress_percent,
        effort_confidence=effort.confidence,
        confidence=confidence,
        effort_source=effort.source,
        evidence_ids=effort.evidence_ids,
        assumptions=tuple(dict.fromkeys(assumptions)),
        reasons=tuple(reasons),
    )
