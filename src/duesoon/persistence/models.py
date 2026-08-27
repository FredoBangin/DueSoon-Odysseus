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
