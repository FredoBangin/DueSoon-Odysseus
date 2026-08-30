"""Canvas-core persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_course_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    course_code: Mapped[str | None] = mapped_column(String(255))
    term: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_type",
            "external_id",
            "content_hash",
            name="uq_source_record_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(50), index=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    ingestion_status: Mapped[str] = mapped_column(String(30), default="ingested")
    parser_version: Mapped[str] = mapped_column(String(30), default="canvas-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    claims: Mapped[list["Claim"]] = relationship(back_populates="source_record")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canvas_assignment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    canonical_title: Mapped[str] = mapped_column(String(1000))
    description_hash: Mapped[str | None] = mapped_column(String(64))
    canvas_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    points_possible: Mapped[float | None] = mapped_column(Float)
    assignment_type: Mapped[str | None] = mapped_column(String(100))
    submission_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    grading_type: Mapped[str | None] = mapped_column(String(100))
    html_url: Mapped[str | None] = mapped_column(Text)
    workflow_state: Mapped[str | None] = mapped_column(String(100))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    canvas_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    course: Mapped[Course] = relationship(back_populates="assignments")
    submission: Mapped["Submission | None"] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", uselist=False
    )
    snapshots: Mapped[list["AssignmentSnapshot"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["AssignmentEvidence"]] = relationship(back_populates="assignment")


class AssignmentSnapshot(Base):
    __tablename__ = "assignment_snapshots"
    __table_args__ = (
        UniqueConstraint("assignment_id", "content_hash", name="uq_assignment_snapshot_content"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    points_possible: Mapped[float | None] = mapped_column(Float)
    submission_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignment: Mapped[Assignment] = relationship(back_populates="snapshots")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), unique=True, index=True
    )
    external_submission_id: Mapped[str | None] = mapped_column(String(64), index=True)
    normalized_status: Mapped[str] = mapped_column(String(30))
    raw_status: Mapped[str | None] = mapped_column(String(100))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    assignment: Mapped[Assignment] = relationship(back_populates="submission")


class Claim(Base):
    """Append-only structured claim extracted from one immutable source version."""

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint(
            "source_record_id",
            "extractor_version",
            "claim_fingerprint",
            name="uq_claim_source_extractor_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="RESTRICT"), index=True
    )
    claim_type: Mapped[str] = mapped_column(String(50), index=True)
    course_hint: Mapped[str | None] = mapped_column(String(500))
    assignment_hint: Mapped[str | None] = mapped_column(String(1000))
    normalized_value: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_locator: Mapped[str | None] = mapped_column(Text)
    author_identity: Mapped[str | None] = mapped_column(String(500))
    author_role: Mapped[str | None] = mapped_column(String(100))
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extraction_method: Mapped[str] = mapped_column(String(50))
    extractor_version: Mapped[str] = mapped_column(String(100))
    extraction_confidence: Mapped[float] = mapped_column(Float)
    validation_status: Mapped[str] = mapped_column(String(30), index=True)
    claim_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    source_record: Mapped[SourceRecord] = relationship(back_populates="claims")
    assignment_links: Mapped[list["AssignmentEvidence"]] = relationship(
        back_populates="claim"
    )


class AssignmentEvidence(Base):
    """Auditable claim-to-assignment match and resolver feature snapshot."""

    __tablename__ = "assignment_evidence"
    __table_args__ = (
        UniqueConstraint("assignment_id", "claim_id", name="uq_assignment_evidence_claim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="RESTRICT"), index=True
    )
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), index=True
    )
    course_match_score: Mapped[float] = mapped_column(Float)
    assignment_match_score: Mapped[float] = mapped_column(Float)
    authority_score: Mapped[float] = mapped_column(Float)
    explicitness_score: Mapped[float] = mapped_column(Float, default=1.0)
    precision: Mapped[str] = mapped_column(String(30), default="unknown")
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    author_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    source_current: Mapped[bool] = mapped_column(Boolean, default=True)
    recency_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    corroboration_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supersedes_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflict_group: Mapped[str | None] = mapped_column(String(100), index=True)
    disposition: Mapped[str] = mapped_column(String(30), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignment: Mapped[Assignment] = relationship(back_populates="evidence")
    claim: Mapped[Claim] = relationship(back_populates="assignment_links")


class AssignmentEffortEstimate(Base):
    """Append-only effort estimate; never alters an academic deadline."""

    __tablename__ = "assignment_effort_estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="RESTRICT"), index=True
    )
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    lower_minutes: Mapped[int] = mapped_column(Integer)
    upper_minutes: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(30))
    source_kind: Mapped[str] = mapped_column(String(50))
    evidence_id: Mapped[str | None] = mapped_column(String(255))
    owner_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(50), default="planning-evidence-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AssignmentProgressObservation(Base):
    """Append-only owner progress observation used only for work planning."""

    __tablename__ = "assignment_progress_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="RESTRICT"), index=True
    )
    percent_complete: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(50), default="owner")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CalendarBusyBlock(Base):
    """Sanitized read-only calendar interval; event titles are never persisted."""

    __tablename__ = "calendar_busy_blocks"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "external_id_hash",
            name="uq_calendar_busy_source_event",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(50), default="google_calendar")
    external_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(50), default="canvas")
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    courses_seen: Mapped[int] = mapped_column(Integer, default=0)
    assignments_seen: Mapped[int] = mapped_column(Integer, default=0)
    submissions_seen: Mapped[int] = mapped_column(Integer, default=0)
    source_versions_created: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    notification_kind: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    rendered_title: Mapped[str] = mapped_column(String(200))
    rendered_body: Mapped[str] = mapped_column(String(1000))
    priority: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReminderEvent(Base):
    __tablename__ = "reminder_events"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "deadline_at",
            "checkpoint_minutes",
            name="uq_reminder_assignment_deadline_checkpoint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id"), index=True
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    checkpoint_minutes: Mapped[int] = mapped_column(Integer)
    reminder_kind: Mapped[str] = mapped_column(String(30), default="standard")
    interval_key: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(Text)
    submission_recheck_status: Mapped[str | None] = mapped_column(String(30))
    submission_rechecked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_deliveries.id"), index=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SchedulerState(Base):
    __tablename__ = "scheduler_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_key: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    successful: Mapped[bool] = mapped_column(Boolean, default=False)


class ModelAssistantSetting(Base):
    """Non-secret, owner-controlled model routing limits.

    Provider credentials remain process secrets and are never persisted here.
    """

    __tablename__ = "model_assistant_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    primary_model: Mapped[str | None] = mapped_column(String(255))
    fallback_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=15.0)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=6000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=700)
    call_budget: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AssistantExchange(Base):
    """Auditable assistant response without prompts, secrets, or raw source payloads."""

    __tablename__ = "assistant_exchanges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[str] = mapped_column(String(30))
    evidence_links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decision_trace: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AssistantFeedback(Base):
    __tablename__ = "assistant_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    exchange_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_exchanges.id", ondelete="RESTRICT"), unique=True, index=True
    )
    verdict: Mapped[str] = mapped_column(String(30))
    correction_prompted: Mapped[bool] = mapped_column(Boolean, default=False)
    what_was_wrong: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class LearningProposal(Base):
    __tablename__ = "learning_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_feedback.id", ondelete="RESTRICT"), unique=True, index=True
    )
    behavior_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), index=True)
    scope_ref: Mapped[str | None] = mapped_column(String(255), index=True)
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    affected_future_behavior: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(100), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningAuditEvent(Base):
    __tablename__ = "learning_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("learning_proposals.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(30), index=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(100), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningReversal(Base):
    __tablename__ = "learning_reversals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("learning_proposals.id", ondelete="RESTRICT"), index=True
    )
    audit_event_id: Mapped[int] = mapped_column(
        ForeignKey("learning_audit_events.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AcademicNote(Base):
    """Owner-authored assignment or course annotation."""

    __tablename__ = "academic_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="SET NULL"), index=True
    )
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AcademicMemory(Base):
    """Explicit owner-approved academic alias or preference."""

    __tablename__ = "academic_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), index=True)
    scope_ref: Mapped[str | None] = mapped_column(String(255), index=True)
    label: Mapped[str] = mapped_column(String(500))
    value: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(50), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
