from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.canvas.sync import SyncSummary
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import Assignment, Course, Submission


class FakeSyncService:
    def sync(self) -> SyncSummary:
        return SyncSummary(
            courses_seen=1,
            assignments_seen=2,
            submissions_seen=2,
            source_versions_created=5,
        )


def build_settings(tmp_path: Path, **overrides: object) -> DueSoonSettings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / 'canvas-api.db').as_posix()}",
    }
    values.update(overrides)
    return DueSoonSettings(_env_file=None, **values)


def test_sync_is_rejected_when_canvas_is_disabled(tmp_path: Path) -> None:
    with TestClient(create_app(build_settings(tmp_path))) as client:
        response = client.post("/api/v1/canvas/sync")

    assert response.status_code == 409
    assert response.json() == {"detail": "Canvas ingestion is disabled"}


def test_sync_requires_configured_api_token(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path,
        canvas_enabled=True,
        canvas_base_url="https://school.instructure.com",
        canvas_access_token="canvas-secret",
        api_token="api-secret",
    )
    app = create_app(settings, canvas_sync_service=FakeSyncService())

    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/canvas/sync")
        unauthorized_courses = client.get("/api/v1/courses")
        authorized = client.post(
            "/api/v1/canvas/sync", headers={"X-API-Token": "api-secret"}
        )
        authorized_courses = client.get(
            "/api/v1/courses", headers={"X-API-Token": "api-secret"}
        )

    assert unauthorized.status_code == 401
    assert unauthorized_courses.status_code == 401
    assert authorized.status_code == 200
    assert authorized_courses.status_code == 200
    assert authorized.json() == {
        "courses_seen": 1,
        "assignments_seen": 2,
        "submissions_seen": 2,
        "source_versions_created": 5,
    }


def test_courses_and_assignments_are_exposed_without_raw_payloads(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    app = create_app(settings, engine=engine)
    observed = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

    with TestClient(app) as client:
        sessions = session_factory(engine)
        with sessions() as session:
            course = Course(
                canvas_course_id="42",
                name="Network Security",
                course_code="CIS-420",
                active=True,
                first_seen_at=observed,
                last_seen_at=observed,
            )
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Lab 1",
                canvas_due_at=datetime(2026, 9, 1, 3, 59, tzinfo=UTC),
                points_possible=25,
                assignment_type="online_upload",
                submission_types=["online_upload"],
                published=True,
                first_seen_at=observed,
                last_seen_at=observed,
            )
            submission = Submission(
                assignment=assignment,
                normalized_status="not_submitted",
                raw_status="unsubmitted",
                missing=False,
                late=False,
                observed_at=observed,
                raw_payload={"private": "must-not-leak"},
            )
            session.add_all([course, assignment, submission])
            session.commit()
            assignment_id = assignment.id

        courses = client.get("/api/v1/courses")
        assignments = client.get("/api/v1/assignments")
        detail = client.get(f"/api/v1/assignments/{assignment_id}")

    assert courses.status_code == 200
    assert courses.json()[0]["canvas_course_id"] == "42"
    assert assignments.status_code == 200
    assert assignments.json()[0]["submission"]["normalized_status"] == "not_submitted"
    assert detail.status_code == 200
    assert "must-not-leak" not in detail.text


def test_assignment_detail_returns_404(tmp_path: Path) -> None:
    with TestClient(create_app(build_settings(tmp_path))) as client:
        response = client.get("/api/v1/assignments/999")

    assert response.status_code == 404
