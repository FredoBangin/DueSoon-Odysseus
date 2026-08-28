"""Canvas-baseline Effective Assignment projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    points_possible: float | None
    submission_status: str
    submitted_at: datetime | None


def project_canvas_assignment(assignment: Assignment) -> EffectiveAssignment:
    submission = assignment.submission
    status = submission.normalized_status if submission is not None else "not_submitted"
    due = assignment.canvas_due_at
    return EffectiveAssignment(
        assignment_id=assignment.id,
        canvas_assignment_id=assignment.canvas_assignment_id,
        canvas_course_id=assignment.course.canvas_course_id,
        course_name=assignment.course.name,
        title=assignment.canonical_title,
        external_url=assignment.html_url,
        canvas_due_at=due,
        effective_due_at=due,
        operational_due_at=due,
        deadline_status="resolved" if due is not None else "unknown",
        deadline_confidence="high" if due is not None else "low",
        deadline_source_summary=("Current Canvas assignment deadline" if due is not None
                                 else "Canvas has no deadline"),
        points_possible=assignment.points_possible,
        submission_status=status,
        submitted_at=submission.submitted_at if submission is not None else None,
    )
