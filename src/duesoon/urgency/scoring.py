"""Explainable urgency-v1 scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

from src.duesoon.assignments.effective import EffectiveAssignment


@dataclass(frozen=True)
class UrgencyBreakdown:
    time_score: int
    value_score: int
    workload_score: int
    due_date_change_score: int
    submission_score: int
    raw_score: int
    total: int
    level: str
    reasons: tuple[str, ...]
    config_version: str = "urgency-v1"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def time_remaining_score(remaining: timedelta | None) -> int:
    if remaining is None or remaining > timedelta(days=7): return 0
    if remaining > timedelta(days=3): return 8
    if remaining > timedelta(hours=24): return 15
    if remaining > timedelta(hours=12): return 25
    if remaining > timedelta(hours=6): return 32
    if remaining > timedelta(hours=1): return 42
    if remaining > timedelta(minutes=15): return 50
    return 55


def _value(points: float | None) -> int:
    if points is None: return 0
    if points <= 10: return 2
    if points <= 25: return 4
    if points <= 50: return 7
    if points <= 100: return 10
    return 15


def score_assignment(item: EffectiveAssignment, all_items: Sequence[EffectiveAssignment],
                     now: datetime, earlier_move_hours: float | None = None) -> UrgencyBreakdown:
    if item.submission_status in {"submitted", "graded"}:
        return UrgencyBreakdown(0, 0, 0, 0, 0, 0, 0, "LOW", ("Work is complete",))
    now = _utc(now)
    due = _utc(item.operational_due_at) if item.operational_due_at else None
    remaining = due - now if due else None
    time_score = time_remaining_score(remaining)
    value_score = _value(item.points_possible)
    nearby = 0
    if due:
        for other in all_items:
            if other.assignment_id == item.assignment_id or other.submission_status in {"submitted", "graded"} or not other.operational_due_at:
                continue
            if abs((_utc(other.operational_due_at) - due).total_seconds()) <= 86400:
                nearby += 1
    workload_score = (0, 4, 8, 12, 15)[min(nearby, 4)]
    change_score = 0 if not earlier_move_hours else (10 if earlier_move_hours > 24 or (remaining and remaining <= timedelta(hours=6)) else 6 if earlier_move_hours >= 6 else 3)
    submission_score = 10 if item.submission_status == "missing" else 5 if item.submission_status == "late" else 0
    raw = time_score + value_score + workload_score + change_score + submission_score
    total = min(raw, 100)
    level = "CRITICAL" if total >= 85 else "HIGH" if total >= 60 else "MEDIUM" if total >= 30 else "LOW"
    reasons = []
    if remaining is None: reasons.append("No precise deadline is available")
    elif remaining.total_seconds() < 0: reasons.append("Overdue and incomplete")
    else: reasons.append(f"Due in {max(0, int(remaining.total_seconds() // 60))} minutes")
    if item.points_possible is not None: reasons.append(f"Worth {item.points_possible:g} points")
    if nearby: reasons.append(f"{nearby} other incomplete assignment(s) due within 24 hours")
    if item.submission_status in {"missing", "late"}: reasons.append(f"Canvas marks this {item.submission_status}")
    return UrgencyBreakdown(time_score, value_score, workload_score, change_score,
                            submission_score, raw, total, level, tuple(reasons))
