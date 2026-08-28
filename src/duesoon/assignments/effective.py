"""Canvas-baseline Effective Assignment projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from src.duesoon.intelligence.deadline_resolver import (
    DeadlineCandidate,
    resolve_deadline,
    source_authority,
)
from src.duesoon.intelligence.evidence import deadline_candidates_from_evidence
from src.duesoon.persistence.models import Assignment


@dataclass(frozen=True)
class EffectiveAssignment:
    assignment_id: int
    canvas_assignment_id: str
    canvas_course_id: str
    course_name: str
    title: str
    external_url: str | None
    canvas_due_at: datetime | None
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    deadline_status: str
    deadline_confidence: str
    deadline_source_summary: str
    deadline_evidence_ids: tuple[str, ...]
    previous_due_at: datetime | None
    deadline_changed_at: datetime | None
    deadline_change_hours: float | None
    points_possible: float | None
    submission_status: str
    submitted_at: datetime | None
    due_at_precision: str = "unknown"
    deadline_resolution_explanation: str = ""
    conflicting_due_at: tuple[datetime, ...] = ()
    persisted_deadline_evidence_count: int = 0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _deadline_history(assignment: Assignment) -> tuple[datetime | None, datetime | None, float | None]:
    snapshots = sorted(assignment.snapshots, key=lambda item: item.observed_at, reverse=True)
    if not snapshots:
        return None, None, None
    current = assignment.canvas_due_at
    previous = next(
        (item.due_at for item in snapshots[1:] if item.due_at != current),
        None,
    )
    if previous is None:
        return None, None, None
    changed_at = snapshots[0].observed_at
    change_hours = None
    if current is not None:
        change_hours = (_utc(previous) - _utc(current)).total_seconds() / 3600
    return previous, changed_at, change_hours


def project_canvas_assignment(
    assignment: Assignment,
    extra_deadline_candidates: Iterable[DeadlineCandidate] = (),
) -> EffectiveAssignment:
    submission = assignment.submission
    status = submission.normalized_status if submission is not None else "not_submitted"
    due = assignment.canvas_due_at
    persisted_candidates = deadline_candidates_from_evidence(assignment.evidence)
    candidates_by_id = {
        candidate.evidence_id: candidate for candidate in persisted_candidates
    }
    candidates_by_id.update(
        {candidate.evidence_id: candidate for candidate in extra_deadline_candidates}
    )
    if due is not None:
        canvas_candidate = DeadlineCandidate(
            evidence_id=f"canvas-assignment:{assignment.canvas_assignment_id}:current",
            due_at=due,
            source_kind="canvas_assignment",
            published_at=assignment.canvas_updated_at or assignment.updated_at,
            authority=source_authority("canvas_assignment"),
        )
        candidates_by_id[canvas_candidate.evidence_id] = canvas_candidate
    resolution = resolve_deadline(candidates_by_id.values())
    previous_due_at, deadline_changed_at, deadline_change_hours = _deadline_history(assignment)
    return EffectiveAssignment(
        assignment_id=assignment.id,
        canvas_assignment_id=assignment.canvas_assignment_id,
        canvas_course_id=assignment.course.canvas_course_id,
        course_name=assignment.course.name,
        title=assignment.canonical_title,
        external_url=assignment.html_url,
        canvas_due_at=due,
        effective_due_at=resolution.effective_due_at,
        operational_due_at=resolution.operational_due_at,
        deadline_status=resolution.status,
        deadline_confidence=resolution.confidence,
        deadline_source_summary=resolution.source_summary,
        deadline_evidence_ids=resolution.evidence_ids,
        previous_due_at=previous_due_at,
        deadline_changed_at=deadline_changed_at,
        deadline_change_hours=deadline_change_hours,
        points_possible=assignment.points_possible,
        submission_status=status,
        submitted_at=submission.submitted_at if submission is not None else None,
        due_at_precision=resolution.precision,
        deadline_resolution_explanation=resolution.explanation,
        conflicting_due_at=resolution.conflicting_due_at,
        persisted_deadline_evidence_count=len(persisted_candidates),
    )
