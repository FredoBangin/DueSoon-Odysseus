"""Public API response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class UrgencyBreakdownResponse(BaseModel):
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
    reasons: list[str]
    config_version: str


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
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    deadline_status: str
    deadline_confidence: str
    deadline_source_summary: str
    deadline_evidence_ids: list[str]
    due_at_precision: str
    deadline_resolution_explanation: str
    conflicting_due_at: list[datetime]
    urgency: UrgencyBreakdownResponse


class EvidenceItemResponse(BaseModel):
    evidence_id: str
    source_system: str
    source_type: str
    claim_type: str
    claimed_due_at: datetime | None
    source_published_at: datetime | None
    precision: str
    validation_status: str
    disposition: str
    authority_score: float
    course_match_score: float
    assignment_match_score: float
    explicitness_score: float
    extraction_reliability: float
    owner_confirmed: bool
    source_current: bool
    supports_current_resolution: bool
    summary: str


class EvidenceInspectionResponse(BaseModel):
    assignment_id: int
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    deadline_status: str
    deadline_confidence: str
    deadline_evidence_ids: list[str]
    due_at_precision: str
    resolution_explanation: str
    conflicting_due_at: list[datetime]
    items: list[EvidenceItemResponse]


class ConfirmDeadlineRequest(BaseModel):
    due_at: datetime


class ConfirmDeadlineResponse(BaseModel):
    created: bool
    evidence_id: str
    inspection: EvidenceInspectionResponse


class SyncResponse(BaseModel):
    courses_seen: int
    assignments_seen: int
    submissions_seen: int
    source_versions_created: int


class TestNotificationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    priority: int = Field(default=3, ge=1, le=5)


class NotificationDeliveryResponse(BaseModel):
    status: str
    delivery_id: int
    provider_message_id: str | None
