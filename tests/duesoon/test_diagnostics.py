from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.diagnostics import DiagnosticsService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    Claim,
    Course,
    SchedulerState,
    SourceRecord,
    Submission,
    SyncRun,
)


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'diagnostics.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
        scheduler_interval_seconds=300,
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    app = create_app(settings, engine=engine)
    return settings, engine, app


def seed(sessions) -> None:
    with sessions() as session:
        course = Course(canvas_course_id="42", name="Private Course Name")
        unknown = Assignment(
            canvas_assignment_id="99",
            course=course,
            canonical_title="Private Assignment Title",
            canvas_due_at=None,
            points_possible=None,
            published=True,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        completed = Assignment(
            canvas_assignment_id="100",
            course=course,
            canonical_title="Private Completed Work",
            canvas_due_at=NOW + timedelta(days=1),
            points_possible=10,
            published=True,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        source = SourceRecord(
            source_system="canvas",
            source_type="conversation",
            external_id="private-message",
            course_id=None,
            source_published_at=NOW - timedelta(hours=1),
            observed_at=NOW - timedelta(hours=1),
            content_hash="private-source",
            raw_payload={"body": "Private professor message"},
            ingestion_status="needs_review",
        )
        claim = Claim(
            source_record=source,
            claim_type="deadline_is",
            assignment_hint="Private Assignment Title",
            normalized_value={"due_at": (NOW + timedelta(days=2)).isoformat()},
            source_locator="Private professor message",
            source_observed_at=NOW - timedelta(hours=1),
            extraction_method="fixture",
            extractor_version="fixture-v1",
            extraction_confidence=0.5,
            validation_status="rejected",
            claim_fingerprint="private-claim",
        )
        session.add_all(
            [
                course,
                unknown,
                completed,
                Submission(
                    assignment=completed,
                    normalized_status="submitted",
                    observed_at=NOW,
                    raw_payload={"private": "submission"},
                ),
                source,
                claim,
                SyncRun(
                    source_system="canvas",
                    status="completed",
                    started_at=NOW - timedelta(minutes=11),
                    finished_at=NOW - timedelta(minutes=10),
                ),
                SchedulerState(
                    key="canvas_reminders",
                    last_successful_at=NOW - timedelta(minutes=15),
                ),
            ]
        )
        session.commit()


def test_diagnostics_are_aggregate_reproducible_and_content_free(tmp_path: Path) -> None:
    settings, engine, _app = build(tmp_path)
    sessions = session_factory(engine)
    seed(sessions)

    value = DiagnosticsService(settings, sessions, clock=lambda: NOW).snapshot()

    assert value["privacy"] == "aggregate_only_no_academic_content"
    assert value["assignments"] == {
        "published": 2,
        "active": 1,
        "completed": 1,
        "without_operational_deadline": 1,
        "deadline_conflicts": 0,
    }
    assert value["urgency"]["bands"] == {
        "LOW": 1,
        "MEDIUM": 0,
        "HIGH": 0,
        "CRITICAL": 0,
    }
    assert value["urgency"]["low_missing_factors"] == {
        "no_operational_deadline": 1,
        "no_points_possible": 1,
        "no_persisted_deadline_evidence": 1,
        "no_submission_observation": 1,
    }
    assert value["evidence"]["unresolved_claims"] == 1
    assert value["operations"]["canvas_sync_age_seconds"] == 600
    assert value["operations"]["scheduler_lag_seconds"] == 900
    assert value["operations"]["scheduler_lag_intervals"] == 3.0
    serialized = str(value)
    for private in (
        "Private Course Name",
        "Private Assignment Title",
        "Private professor message",
    ):
        assert private not in serialized

    engine.dispose()


def test_diagnostics_endpoint_requires_owner_session(tmp_path: Path) -> None:
    _settings, engine, app = build(tmp_path)
    seed(session_factory(engine))

    with TestClient(app, base_url="https://due.test") as client:
        assert client.get("/api/v1/dashboard/diagnostics").status_code == 401
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        assert response.status_code == 200
        diagnostics = client.get("/api/v1/dashboard/diagnostics")

    assert diagnostics.status_code == 200
    assert diagnostics.json()["privacy"] == "aggregate_only_no_academic_content"
    assert "Private Course Name" not in diagnostics.text
    engine.dispose()
