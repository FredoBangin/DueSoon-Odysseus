"""Deterministic, explainable urgency-v2 orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Sequence

from src.duesoon.assignments.effective import EffectiveAssignment
from src.duesoon.urgency.config import DEFAULT_CONFIG, UrgencyConfig
from src.duesoon.urgency.explanations import due_reason, utc
from src.duesoon.urgency.factors import (
    COMPLETE_STATES,
    INACTIVE_STATES,
    deadline_risk_factor,
    due_date_change_factor,
    overdue_factor,
    submission_factor,
    time_factor,
    value_factor,
    workload_factor,
)


@dataclass(frozen=True)
class UrgencyBreakdown:
    time_score: int
    value_score: int
    workload_score: int
    deadline_risk_score: int
    due_date_change_score: int
    submission_score: int
    overdue_score: int
    raw_score: int
    total: int
    level: str
    reasons: tuple[str, ...]
    config_version: str = DEFAULT_CONFIG.version

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def time_remaining_score(
    remaining: timedelta | None,
    config: UrgencyConfig = DEFAULT_CONFIG,
) -> int:
    """Compatibility helper exposing urgency-v2 time pressure."""

    return time_factor(remaining, config).score


def score_assignment(item: EffectiveAssignment, all_items: Sequence[EffectiveAssignment],
                     now: datetime, earlier_move_hours: float | None = None,
                     config: UrgencyConfig = DEFAULT_CONFIG) -> UrgencyBreakdown:
    """Score one effective assignment without AI, I/O, or wall-clock access."""

    status = item.submission_status.lower()
    if status in COMPLETE_STATES | INACTIVE_STATES:
        reason = "Work is complete" if status in COMPLETE_STATES else "Assignment is cancelled"
        return UrgencyBreakdown(0, 0, 0, 0, 0, 0, 0, 0, 0, "LOW", (reason,), config.version)

    now = utc(now)
    due = utc(item.operational_due_at) if item.operational_due_at else None
    remaining = due - now if due else None

    time_result = time_factor(remaining, config)
    value_result = value_factor(item.points_possible, config)
    workload_result = workload_factor(item, all_items, config)
    deadline_result = deadline_risk_factor(item, config)
    change_result = due_date_change_factor(
        item, remaining, now, config, earlier_move_hours,
    )
    submission_result = submission_factor(status, config)
    overdue_result = overdue_factor(remaining, config)
    factors = (
        time_result,
        value_result,
        workload_result,
        deadline_result,
        change_result,
        submission_result,
        overdue_result,
    )

    raw = sum(factor.score for factor in factors)
    total = max(0, min(raw, 100))
    if total >= config.critical_threshold:
        level = "CRITICAL"
    elif total >= config.high_threshold:
        level = "HIGH"
    elif total >= config.medium_threshold:
        level = "MEDIUM"
    else:
        level = "LOW"

    reasons = [due_reason(remaining)]
    reasons.extend(reason for factor in factors for reason in factor.reasons)
    return UrgencyBreakdown(
        time_score=time_result.score,
        value_score=value_result.score,
        workload_score=workload_result.score,
        deadline_risk_score=deadline_result.score,
        due_date_change_score=change_result.score,
        submission_score=submission_result.score,
        overdue_score=overdue_result.score,
        raw_score=raw,
        total=total,
        level=level,
        reasons=tuple(reasons),
        config_version=config.version,
    )
