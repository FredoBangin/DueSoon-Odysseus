"""Validated configuration for deterministic urgency scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UrgencyConfig:
    """All urgency weights and thresholds in one versioned policy object."""

    version: str = "urgency-v2"
    time_max: int = 55
    value_max: int = 15
    workload_max: int = 15
    deadline_risk_max: int = 10
    due_date_change_max: int = 10
    submission_max: int = 10
    overdue_max: int = 10
    workload_window_hours: float = 24.0
    change_awareness_hours: float = 48.0
    overdue_change_expiry_hours: float = 72.0
    medium_threshold: int = 30
    high_threshold: int = 60
    critical_threshold: int = 85

    def __post_init__(self) -> None:
        factor_caps = (
            self.time_max,
            self.value_max,
            self.workload_max,
            self.deadline_risk_max,
            self.due_date_change_max,
            self.submission_max,
            self.overdue_max,
        )
        if not self.version.strip():
            raise ValueError("urgency config version cannot be empty")
        if any(cap < 0 for cap in factor_caps):
            raise ValueError("urgency factor caps cannot be negative")
        if self.workload_window_hours <= 0:
            raise ValueError("workload window must be positive")
        if self.change_awareness_hours <= 0 or self.overdue_change_expiry_hours <= 0:
            raise ValueError("change expiry windows must be positive")
        if not 0 < self.medium_threshold < self.high_threshold < self.critical_threshold <= 100:
            raise ValueError("urgency thresholds must increase within 1..100")


DEFAULT_CONFIG = UrgencyConfig()
