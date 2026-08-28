"""Idempotent Canvas synchronization service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.canvas.normalize import (
    normalize_assignment,
    normalize_course,
    normalize_submission,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentSnapshot,
    Course,
    SourceRecord,
    Submission,
    SyncRun,
)


class CanvasReader(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...

    def list_assignments(self, course_id: str) -> list[dict[str, Any]]: ...

    def get_submission(
        self, course_id: str, assignment_id: str
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SyncSummary:
    courses_seen: int = 0
    assignments_seen: int = 0
    submissions_seen: int = 0
    source_versions_created: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class CanvasSyncService:
    def __init__(
        self,
        client: CanvasReader,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.clock = clock

    def sync(self) -> SyncSummary:
        started_at = self.clock()
        try:
            with self.sessions() as session:
                run = SyncRun(source_system="canvas", status="running", started_at=started_at)
                session.add(run)
                session.flush()

                courses_seen = assignments_seen = submissions_seen = source_versions = 0
                for raw_course in self.client.list_courses():
                    courses_seen += 1
                    course = self._upsert_course(session, raw_course, started_at)
                    _, created = self._source_record(
                        session,
                        source_type="course",
                        external_id=course.canvas_course_id,
                        course_id=course.id,
                        raw_payload=raw_course,
                        observed_at=started_at,
                    )
                    source_versions += int(created)

                    for raw_assignment in self.client.list_assignments(course.canvas_course_id):
                        assignments_seen += 1
                        submissions_seen += 1
                        assignment_source, created = self._source_record(
                            session,
                            source_type="assignment",
                            external_id=str(raw_assignment["id"]),
                            course_id=course.id,
                            raw_payload=raw_assignment,
                            observed_at=started_at,
                        )
                        source_versions += int(created)
                        assignment = self._upsert_assignment(
                            session, course, raw_assignment, started_at
                        )
                        self._add_snapshot(
                            session,
                            assignment,
                            assignment_source,
                            normalize_assignment(raw_assignment),
                            started_at,
                        )
                        submission_payload = raw_assignment.get("submission") or {}
                        _, created = self._source_record(
                            session,
                            source_type="submission",
                            external_id=str(
                                submission_payload.get("id")
                                or f"{assignment.canvas_assignment_id}:current"
                            ),
                            course_id=course.id,
                            raw_payload=submission_payload,
                            observed_at=started_at,
                        )
                        source_versions += int(created)
                        self._upsert_submission(
                            session, assignment, submission_payload, started_at
                        )

                summary = SyncSummary(
                    courses_seen=courses_seen,
                    assignments_seen=assignments_seen,
                    submissions_seen=submissions_seen,
                    source_versions_created=source_versions,
                )
                run.status = "completed"
                run.finished_at = self.clock()
                run.courses_seen = summary.courses_seen
                run.assignments_seen = summary.assignments_seen
                run.submissions_seen = summary.submissions_seen
                run.source_versions_created = summary.source_versions_created
                session.commit()
                return summary
        except Exception as exc:
            with self.sessions() as failure_session:
                failure_session.add(
                    SyncRun(
                        source_system="canvas",
                        status="failed",
                        started_at=started_at,
                        finished_at=self.clock(),
                        error_code=type(exc).__name__,
                    )
                )
                failure_session.commit()
            raise

    def refresh_submission(self, assignment_id: int) -> str:
        observed_at = self.clock()
        with self.sessions() as session:
            assignment = session.get(Assignment, assignment_id)
            if assignment is None:
                raise LookupError("assignment not found")
            course = session.get(Course, assignment.course_id)
            if course is None:
                raise LookupError("course not found")

            raw_submission = self.client.get_submission(
                course.canvas_course_id,
                assignment.canvas_assignment_id,
            )
            self._source_record(
                session,
                source_type="submission",
                external_id=str(
                    raw_submission.get("id")
                    or f"{assignment.canvas_assignment_id}:current"
                ),
                course_id=course.id,
                raw_payload=raw_submission,
                observed_at=observed_at,
            )
            submission = self._upsert_submission(
                session,
                assignment,
                raw_submission,
                observed_at,
            )
            session.commit()
            return submission.normalized_status

    @staticmethod
    def _upsert_course(
        session: Session, raw: dict[str, Any], observed_at: datetime
    ) -> Course:
        normalized = normalize_course(raw)
        course = session.scalar(
            select(Course).where(
                Course.canvas_course_id == normalized["canvas_course_id"]
            )
        )
        if course is None:
            course = Course(
                **normalized,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            session.add(course)
        else:
            for key, value in normalized.items():
                setattr(course, key, value)
            course.last_seen_at = observed_at
        session.flush()
        return course

    @staticmethod
    def _upsert_assignment(
        session: Session,
        course: Course,
        raw: dict[str, Any],
        observed_at: datetime,
    ) -> Assignment:
        normalized = normalize_assignment(raw)
        assignment = session.scalar(
            select(Assignment).where(
                Assignment.canvas_assignment_id
                == normalized["canvas_assignment_id"]
            )
        )
        parsed = {
            key: _parse_datetime(normalized[key])
            for key in ("canvas_due_at", "unlock_at", "lock_at", "canvas_updated_at")
        }
        values = {**normalized, **parsed}
        if assignment is None:
            assignment = Assignment(
                **values,
                course=course,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            session.add(assignment)
        else:
            for key, value in values.items():
                setattr(assignment, key, value)
            assignment.course_id = course.id
            assignment.last_seen_at = observed_at
        session.flush()
        return assignment

    @staticmethod
    def _upsert_submission(
        session: Session,
        assignment: Assignment,
        raw: dict[str, Any],
        observed_at: datetime,
    ) -> Submission:
        normalized = normalize_submission(raw)
        submission = session.scalar(
            select(Submission).where(Submission.assignment_id == assignment.id)
        )
        values = {
            **normalized,
            "submitted_at": _parse_datetime(normalized["submitted_at"]),
            "graded_at": _parse_datetime(normalized["graded_at"]),
            "observed_at": observed_at,
            "raw_payload": raw,
        }
        if submission is None:
            submission = Submission(assignment=assignment, **values)
            session.add(submission)
        else:
            for key, value in values.items():
                setattr(submission, key, value)
        session.flush()
        return submission

    @staticmethod
    def _add_snapshot(
        session: Session,
        assignment: Assignment,
        source: SourceRecord,
        normalized: dict[str, Any],
        observed_at: datetime,
    ) -> None:
        content_hash = _content_hash(normalized)
        existing = session.scalar(
            select(AssignmentSnapshot.id).where(
                AssignmentSnapshot.assignment_id == assignment.id,
                AssignmentSnapshot.content_hash == content_hash,
            )
        )
        if existing is not None:
            return
        session.add(
            AssignmentSnapshot(
                assignment_id=assignment.id,
                source_record_id=source.id,
                content_hash=content_hash,
                normalized_payload=normalized,
                due_at=_parse_datetime(normalized["canvas_due_at"]),
                points_possible=normalized["points_possible"],
                submission_types=normalized["submission_types"],
                observed_at=observed_at,
            )
        )

    @staticmethod
    def _source_record(
        session: Session,
        *,
        source_type: str,
        external_id: str,
        course_id: int,
        raw_payload: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[SourceRecord, bool]:
        content_hash = _content_hash(raw_payload)
        record = session.scalar(
            select(SourceRecord).where(
                SourceRecord.source_system == "canvas",
                SourceRecord.source_type == source_type,
                SourceRecord.external_id == external_id,
                SourceRecord.content_hash == content_hash,
            )
        )
        if record is not None:
            return record, False
        version = session.scalar(
            select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_system == "canvas",
                SourceRecord.source_type == source_type,
                SourceRecord.external_id == external_id,
            )
        )
        record = SourceRecord(
            source_system="canvas",
            source_type=source_type,
            external_id=external_id,
            course_id=course_id,
            observed_at=observed_at,
            content_hash=content_hash,
            version=int(version or 0) + 1,
            raw_payload=raw_payload,
        )
        session.add(record)
        session.flush()
        return record, True


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
