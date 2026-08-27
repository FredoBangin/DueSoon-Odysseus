"""Public API response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CourseResponse(BaseModel):
    id: int
    canvas_course_id: str
    name: str
    course_code: str | None
    term: str | None
    timezone: str | None
    active: bool


class SubmissionResponse(BaseModel):
    normalized_status: str
    raw_status: str | None
    submitted_at: datetime | None
    graded_at: datetime | None
    missing: bool
    late: bool


class AssignmentResponse(BaseModel):
    id: int
    canvas_assignment_id: str
    course_id: int
    canvas_course_id: str
    course_name: str
    canonical_title: str
    canvas_due_at: datetime | None
    unlock_at: datetime | None
    lock_at: datetime | None
    points_possible: float | None
    assignment_type: str | None
    submission_types: list[str]
    grading_type: str | None
    html_url: str | None
    published: bool
    submission: SubmissionResponse | None


class SyncResponse(BaseModel):
    courses_seen: int
    assignments_seen: int
    submissions_seen: int
    source_versions_created: int
