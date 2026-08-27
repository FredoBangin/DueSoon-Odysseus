from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentSnapshot,
    Course,
    SourceRecord,
    Submission,
    SyncRun,
)


class FakeCanvasClient:
    def list_courses(self):
        return [
            {
                "id": 42,
                "name": "Network Security",
                "course_code": "CIS-420",
                "workflow_state": "available",
                "term": {"name": "Fall 2026"},
            }
        ]

    def list_assignments(self, course_id: str):
        assert course_id == "42"
        return [
            {
                "id": 99,
                "name": "Lab 1",
                "description": "Complete the lab",
                "due_at": "2026-09-01T03:59:00Z",
                "points_possible": 25,
                "submission_types": ["online_upload"],
                "grading_type": "points",
                "published": True,
                "workflow_state": "published",
                "updated_at": "2026-08-25T12:00:00Z",
                "submission": {
                    "id": 501,
                    "workflow_state": "unsubmitted",
                    "missing": False,
                    "late": False,
                },
            }
        ]


def build_service():
    engine = create_engine_from_settings(
        DueSoonSettings(_env_file=None, database_url="sqlite:///:memory:")
    )
    create_schema(engine)
    sessions = session_factory(engine)
    service = CanvasSyncService(
        FakeCanvasClient(),
        sessions,
        clock=lambda: datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
    )
    return engine, sessions, service


def scalar_count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_sync_persists_canvas_course_assignment_and_submission() -> None:
    engine, sessions, service = build_service()
    try:
        summary = service.sync()
        with sessions() as session:
            course = session.scalar(select(Course))
            assignment = session.scalar(select(Assignment))
            submission = session.scalar(select(Submission))
            assert course is not None and course.name == "Network Security"
            assert assignment is not None and assignment.canvas_due_at is not None
            assert assignment.course_id == course.id
            assert submission is not None and submission.normalized_status == "not_submitted"
            assert summary.courses_seen == 1
            assert summary.assignments_seen == 1
            assert summary.submissions_seen == 1
            assert summary.source_versions_created == 3
    finally:
        engine.dispose()


def test_repeated_sync_is_idempotent() -> None:
    engine, sessions, service = build_service()
    try:
        service.sync()
        second = service.sync()

        with sessions() as session:
            assert scalar_count(session, Course) == 1
            assert scalar_count(session, Assignment) == 1
            assert scalar_count(session, Submission) == 1
            assert scalar_count(session, SourceRecord) == 3
            assert scalar_count(session, AssignmentSnapshot) == 1
            assert scalar_count(session, SyncRun) == 2
        assert second.source_versions_created == 0
    finally:
        engine.dispose()
