"""Pure bounded factors used by urgency-v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from src.duesoon.assignments.effective import EffectiveAssignment
from src.duesoon.urgency.config import UrgencyConfig
from src.duesoon.urgency.explanations import compact_duration, timestamp_label, utc


COMPLETE_STATES = frozenset({"submitted", "graded"})
INACTIVE_STATES = frozenset({"cancelled"})


@dataclass(frozen=True)
class FactorResult:
    score: int
    maximum: int
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.score <= self.maximum:
            raise ValueError(f"factor score {self.score} outside 0..{self.maximum}")


def _interpolate(remaining_hours: float, anchors: Sequence[tuple[float, int]]) -> int:
    """Interpolate a monotonic time curve between reviewed policy anchors."""

    for index, (hours, score) in enumerate(anchors):
        if remaining_hours >= hours:
            if index == 0:
                return score
            higher_hours, higher_score = anchors[index - 1]
            span = higher_hours - hours
            progress = (higher_hours - remaining_hours) / span
            return round(higher_score + progress * (score - higher_score))
    return anchors[-1][1]


def time_factor(remaining: timedelta | None, config: UrgencyConfig) -> FactorResult:
    if remaining is None:
        return FactorResult(0, config.time_max)
    if remaining.total_seconds() < 0:
        return FactorResult(config.time_max, config.time_max)

    hours = remaining.total_seconds() / 3600
    # More than seven days remains zero as specified. Inside seven days, interpolation
    # removes large score jumps while retaining reviewed checkpoint anchors.
    if hours > 7 * 24:
        score = 0
    else:
        baseline = ((7 * 24, 8), (3 * 24, 15), (24, 25), (12, 32),
                    (6, 42), (1, 50), (0.25, 55), (0, 55))
        score = _interpolate(hours, baseline)
    score = min(score, config.time_max)
    return FactorResult(score, config.time_max)


def value_factor(points: float | None, config: UrgencyConfig) -> FactorResult:
    if points is None or points < 0:
        return FactorResult(0, config.value_max)
    if points <= 10:
        score = 2
    elif points <= 25:
        score = 4
    elif points <= 50:
        score = 7
    elif points <= 100:
        score = 10
    else:
        score = 15
    score = min(score, config.value_max)
    return FactorResult(score, config.value_max, (f"Worth {points:g} points",))


def workload_factor(
    item: EffectiveAssignment,
    all_items: Sequence[EffectiveAssignment],
    config: UrgencyConfig,
) -> FactorResult:
    if item.operational_due_at is None:
        return FactorResult(0, config.workload_max)

    due = utc(item.operational_due_at)
    nearby = 0
    pressure = 0
    for other in all_items:
        if other.assignment_id == item.assignment_id:
            continue
        if other.submission_status in COMPLETE_STATES | INACTIVE_STATES:
            continue
        if other.operational_due_at is None:
            continue
        distance_hours = abs((utc(other.operational_due_at) - due).total_seconds()) / 3600
        if distance_hours > config.workload_window_hours:
            continue
        nearby += 1
        if distance_hours <= 6:
            pressure += 5
        elif distance_hours <= 12:
            pressure += 4
        else:
            pressure += 3

    score = min(pressure, config.workload_max)
    reasons = ()
    if nearby:
        noun = "assignment" if nearby == 1 else "assignments"
        reasons = (f"{nearby} other incomplete {noun} due within 24 hours",)
    return FactorResult(score, config.workload_max, reasons)


def deadline_risk_factor(item: EffectiveAssignment, config: UrgencyConfig) -> FactorResult:
    status = item.deadline_status.lower()
    confidence = item.deadline_confidence.lower()
    if status == "conflicted":
        return FactorResult(config.deadline_risk_max, config.deadline_risk_max,
                            ("Credible deadline sources conflict; earliest candidate is protective",))
    if status == "provisional":
        score = min(5, config.deadline_risk_max)
        return FactorResult(score, config.deadline_risk_max,
                            (f"Deadline is provisional with {confidence} confidence",))
    if status == "resolved" and confidence == "low":
        score = min(3, config.deadline_risk_max)
        return FactorResult(score, config.deadline_risk_max,
                            ("Resolved deadline has low confidence",))
    return FactorResult(0, config.deadline_risk_max)


def due_date_change_factor(
    item: EffectiveAssignment,
    remaining: timedelta | None,
    now: datetime,
    config: UrgencyConfig,
    earlier_move_hours: float | None,
) -> FactorResult:
    move_hours = earlier_move_hours
    if move_hours is None:
        move_hours = item.deadline_change_hours
        if item.deadline_changed_at is not None:
            age = utc(now) - utc(item.deadline_changed_at)
            if age < timedelta(0) or age > timedelta(hours=config.change_awareness_hours):
                move_hours = None

    if move_hours is None or move_hours <= 0:
        return FactorResult(0, config.due_date_change_max)
    if remaining is not None and remaining < -timedelta(hours=config.overdue_change_expiry_hours):
        return FactorResult(0, config.due_date_change_max)

    if move_hours > 24 or (remaining is not None and remaining <= timedelta(hours=6)):
        score = 10
    elif move_hours >= 6 or (remaining is not None and remaining <= timedelta(hours=24)):
        score = 6
    else:
        score = 3
    score = min(score, config.due_date_change_max)

    reason = f"Deadline moved {compact_duration(timedelta(hours=move_hours))} earlier"
    if item.previous_due_at is not None and item.operational_due_at is not None:
        reason += (f" from {timestamp_label(item.previous_due_at)}"
                   f" to {timestamp_label(item.operational_due_at)}")
    return FactorResult(score, config.due_date_change_max, (reason,))


def submission_factor(status: str, config: UrgencyConfig) -> FactorResult:
    normalized = status.lower()
    if normalized == "missing":
        return FactorResult(min(10, config.submission_max), config.submission_max,
                            ("Canvas marks this assignment missing",))
    if normalized == "late":
        return FactorResult(min(5, config.submission_max), config.submission_max,
                            ("Canvas marks this assignment late",))
    return FactorResult(0, config.submission_max)


def overdue_factor(remaining: timedelta | None, config: UrgencyConfig) -> FactorResult:
    if remaining is None or remaining.total_seconds() >= 0:
        return FactorResult(0, config.overdue_max)
    overdue_hours = -remaining.total_seconds() / 3600
    # Explicit overdue pressure grows from 2 to 10 over 72 hours, bounded forever.
    score = min(config.overdue_max, max(2, round(2 + overdue_hours * 8 / 72)))
    return FactorResult(score, config.overdue_max)
