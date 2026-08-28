"""Focused regression tests for deterministic urgency-v2 intelligence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.duesoon.assignments.effective import EffectiveAssignment
from src.duesoon.urgency.config import DEFAULT_CONFIG, UrgencyConfig
from src.duesoon.urgency.factors import workload_factor
from src.duesoon.urgency.scoring import score_assignment, time_remaining_score


NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def assignment(
    assignment_id: int = 1,
    *,
    due_in: timedelta | None = timedelta(hours=5),
    points: float | None = 100,
    status: str = "not_submitted",
    deadline_status: str = "resolved",
    confidence: str = "high",
    previous_due_at: datetime | None = None,
    changed_at: datetime | None = None,
    change_hours: float | None = None,
) -> EffectiveAssignment:
    due = NOW + due_in if due_in is not None else None
    return EffectiveAssignment(
        assignment_id=assignment_id,
        canvas_assignment_id=str(1000 + assignment_id),
        canvas_course_id="course-1",
        course_name="Network Security",
        title=f"Assignment {assignment_id}",
        external_url=None,
        canvas_due_at=due,
        effective_due_at=due,
        operational_due_at=due,
        deadline_status=deadline_status,
        deadline_confidence=confidence,
        deadline_source_summary="current Canvas assignment",
        deadline_evidence_ids=(f"evidence-{assignment_id}",),
        previous_due_at=previous_due_at,
        deadline_changed_at=changed_at,
        deadline_change_hours=change_hours,
        points_possible=points,
        submission_status=status,
        submitted_at=NOW if status in {"submitted", "graded"} else None,
    )


def test_time_pressure_is_bounded_monotonic_and_contextual_inside_seven_days() -> None:
    samples = (
        timedelta(days=8), timedelta(days=7), timedelta(days=5), timedelta(days=3),
        timedelta(hours=24), timedelta(hours=12), timedelta(hours=6),
        timedelta(hours=1), timedelta(minutes=15), timedelta(0), timedelta(minutes=-1),
    )
    scores = [time_remaining_score(value) for value in samples]
    assert scores == sorted(scores)
    assert scores[0] == 0
    assert scores[1] == 8
    assert 8 < scores[2] < 15
    assert scores[-1] == DEFAULT_CONFIG.time_max
    assert time_remaining_score(None) == 0


@pytest.mark.parametrize("status", ["submitted", "graded"])
def test_completed_work_overrides_every_factor(status: str) -> None:
    item = assignment(
        due_in=timedelta(days=-2),
        points=500,
        status=status,
        deadline_status="conflicted",
        previous_due_at=NOW + timedelta(days=2),
        changed_at=NOW,
        change_hours=96,
    )
    nearby = [assignment(index, due_in=timedelta(hours=1)) for index in range(2, 7)]
    result = score_assignment(item, [item, *nearby], NOW)
    assert result.total == 0
    assert result.raw_score == 0
    assert result.level == "LOW"
    assert all(value == 0 for name, value in result.to_dict().items() if name.endswith("_score"))
    assert result.reasons == ("Work is complete",)


def test_full_context_produces_explainable_factor_breakdown() -> None:
    due = NOW + timedelta(hours=5)
    item = assignment(
        due_in=timedelta(hours=5),
        status="missing",
        deadline_status="conflicted",
        confidence="medium",
        previous_due_at=due + timedelta(hours=30),
        changed_at=NOW - timedelta(hours=1),
        change_hours=30,
    )
    others = [
        assignment(2, due_in=timedelta(hours=6)),
        assignment(3, due_in=timedelta(hours=15)),
        assignment(4, due_in=timedelta(hours=28)),
    ]
    result = score_assignment(item, [item, *others], NOW)
    assert result.time_score > 42
    assert result.value_score == 10
    assert result.workload_score == 12
    assert result.deadline_risk_score == 10
    assert result.due_date_change_score == 10
    assert result.submission_score == 10
    assert result.overdue_score == 0
    assert result.raw_score == sum((
        result.time_score, result.value_score, result.workload_score,
        result.deadline_risk_score, result.due_date_change_score,
        result.submission_score, result.overdue_score,
    ))
    assert result.total <= 100
    assert result.level == "CRITICAL"
    joined = " | ".join(result.reasons)
    assert "Due in 5h" in joined
    assert "deadline sources conflict" in joined
    assert "Deadline moved 1d 6h earlier" in joined
    assert "3 other incomplete assignments" in joined
    assert "missing" in joined
    assert result.config_version == "urgency-v2"


def test_workload_is_weighted_by_proximity_and_excludes_ineligible_work() -> None:
    item = assignment()
    items = [
        item,
        assignment(2, due_in=timedelta(hours=6)),       # one hour away: 5
        assignment(3, due_in=timedelta(hours=14)),      # nine hours away: 4
        assignment(4, due_in=timedelta(hours=25)),      # twenty hours away: 3
        assignment(5, due_in=timedelta(hours=30)),      # outside window
        assignment(6, due_in=timedelta(hours=5), status="submitted"),
        assignment(7, due_in=timedelta(hours=5), status="graded"),
        assignment(8, due_in=timedelta(hours=5), status="cancelled"),
        assignment(9, due_in=None),
    ]
    result = workload_factor(item, items, DEFAULT_CONFIG)
    assert result.score == 12
    assert result.reasons == ("3 other incomplete assignments due within 24 hours",)


@pytest.mark.parametrize(
    ("deadline_status", "confidence", "expected"),
    (("resolved", "high", 0), ("resolved", "low", 3),
     ("provisional", "medium", 5), ("conflicted", "high", 10),
     ("unknown", "low", 0)),
)
def test_deadline_confidence_and_conflict_have_bounded_policy(
    deadline_status: str, confidence: str, expected: int,
) -> None:
    result = score_assignment(
        assignment(deadline_status=deadline_status, confidence=confidence), [], NOW,
    )
    assert result.deadline_risk_score == expected
    assert 0 <= result.deadline_risk_score <= DEFAULT_CONFIG.deadline_risk_max


def test_due_date_move_bonus_expires_and_later_moves_never_inflate() -> None:
    previous = NOW + timedelta(days=2)
    recent = assignment(
        due_in=timedelta(hours=12),
        previous_due_at=previous,
        changed_at=NOW - timedelta(hours=47),
        change_hours=20,
    )
    expired = replace(recent, deadline_changed_at=NOW - timedelta(hours=49))
    later = replace(recent, deadline_change_hours=-20)
    assert score_assignment(recent, [], NOW).due_date_change_score == 6
    assert score_assignment(expired, [], NOW).due_date_change_score == 0
    assert score_assignment(later, [], NOW).due_date_change_score == 0


def test_explicit_move_context_remains_backwards_compatible() -> None:
    item = assignment(change_hours=None, changed_at=None)
    assert score_assignment(item, [], NOW, earlier_move_hours=30).due_date_change_score == 10


def test_overdue_pressure_is_explicit_growing_and_bounded() -> None:
    recent = score_assignment(assignment(due_in=timedelta(minutes=-1), points=None), [], NOW)
    old = score_assignment(assignment(due_in=timedelta(days=-10), points=None), [], NOW)
    assert recent.time_score == DEFAULT_CONFIG.time_max
    assert recent.overdue_score == 2
    assert old.overdue_score == DEFAULT_CONFIG.overdue_max
    assert "Overdue by" in old.reasons[0]
    assert 0 <= old.total <= 100


def test_missing_deadline_stays_explainable_without_inventing_time_pressure() -> None:
    result = score_assignment(
        assignment(due_in=None, points=120, status="missing", deadline_status="unknown",
                   confidence="low"),
        [],
        NOW,
    )
    assert result.time_score == 0
    assert result.overdue_score == 0
    assert result.value_score == 15
    assert result.submission_score == 10
    assert result.total == 25
    assert result.level == "LOW"
    assert result.reasons[0] == "No precise operational deadline is available"


def test_public_score_clamps_and_thresholds_come_from_validated_config() -> None:
    item = assignment(due_in=timedelta(days=-1), points=500, status="missing",
                      deadline_status="conflicted")
    nearby = [assignment(index, due_in=timedelta(days=-1)) for index in range(2, 7)]
    result = score_assignment(item, [item, *nearby], NOW, earlier_move_hours=48)
    assert result.raw_score > 100
    assert result.total == 100
    assert result.level == "CRITICAL"

    custom = UrgencyConfig(medium_threshold=10, high_threshold=20, critical_threshold=30)
    custom_result = score_assignment(assignment(due_in=None, points=50), [], NOW, config=custom)
    assert custom_result.total == 7
    assert custom_result.level == "LOW"
    with pytest.raises(ValueError, match="thresholds"):
        UrgencyConfig(medium_threshold=60, high_threshold=30)


def test_naive_timestamps_are_normalized_and_serialization_is_stable() -> None:
    naive_now = NOW.replace(tzinfo=None)
    item = replace(assignment(), operational_due_at=(NOW + timedelta(hours=5)).replace(tzinfo=None))
    payload = score_assignment(item, [item], naive_now).to_dict()
    assert payload["config_version"] == "urgency-v2"
    assert isinstance(payload["reasons"], list)
    assert payload["total"] == min(payload["raw_score"], 100)
