from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.intelligence.identity import ProfessorIdentityService
from src.duesoon.intelligence.pipeline import (
    AcademicClaim,
    CanvasEvidencePipeline,
)
from src.duesoon.intelligence.service import EvidenceInspectionService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    Course,
    CourseInstructorIdentity,
    SourceRecord,
)


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)
NEW_DUE = NOW + timedelta(days=2)


class Extractor:
    method = "fixture"
    version = "fixture-v1"

    def __init__(self, claims):
        self.claims = tuple(claims)

    def extract(self, source):
        return self.claims


def database(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'identity.db').as_posix()}",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    return engine, session_factory(engine)


def test_owner_verified_professor_email_auto_scopes_future_gmail_claim(
    tmp_path: Path,
) -> None:
    engine, sessions = database(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="42", name="Network Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Midterm Test",
                canvas_due_at=None,
                published=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            source = SourceRecord(
                source_system="gmail",
                source_type="message",
                external_id="gmail-midterm",
                course_id=None,
                source_published_at=NOW,
                observed_at=NOW,
                content_hash="gmail-midterm",
                raw_payload={
                    "subject": "Midterm Test date",
                    "from": "Professor Name <professor@example.edu>",
                    "body": "Midterm Test is due August 31 at 8:00 AM EDT.",
                },
            )
            session.add_all([assignment, source])
            session.commit()
            course_id, assignment_id = course.id, assignment.id

        safe = ProfessorIdentityService(sessions).verify(
            course_id=course_id,
            email="Professor@Example.edu",
            source_kind="owner",
        )
        claim = AcademicClaim(
            claim_type="deadline_is",
            assignment_hint="Midterm Test",
            canvas_assignment_id=None,
            normalized_value={
                "due_at": NEW_DUE.isoformat(),
                "precision": "exact_datetime",
            },
            source_locator="Midterm Test is due August 31 at 8:00 AM EDT.",
            confidence_band="high",
            explicitness="explicit",
        )
        summary = CanvasEvidencePipeline(sessions, Extractor((claim,))).process_pending()

        assert safe["sender"] == "p***@example.edu"
        assert "professor@example.edu" not in str(safe).casefold()
        assert summary.evidence_created == 1
        assert summary.needs_review == 0
        assert EvidenceInspectionService(sessions).inspect(assignment_id).effective_due_at == NEW_DUE
        with sessions() as session:
            identity = session.scalar(select(CourseInstructorIdentity))
            link = session.scalar(select(AssignmentEvidence))
            assert identity.email_hash != "professor@example.edu"
            assert link is not None and link.author_verified is True
            assert link.disposition == "admitted"
    finally:
        engine.dispose()


def test_syllabus_professor_claim_requires_owner_confirmation(tmp_path: Path) -> None:
    engine, sessions = database(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="42", name="Network Security")
            session.add(course)
            session.flush()
            source = SourceRecord(
                source_system="canvas",
                source_type="page",
                external_id="syllabus",
                course_id=course.id,
                source_published_at=NOW,
                observed_at=NOW,
                content_hash="syllabus",
                raw_payload={
                    "title": "Syllabus",
                    "body": "Instructor email: professor@example.edu",
                },
            )
            session.add(source)
            session.commit()
        claim = AcademicClaim(
            claim_type="professor_identity",
            assignment_hint=None,
            normalized_value={"email": "professor@example.edu"},
            source_locator="professor@example.edu",
            confidence_band="high",
            explicitness="explicit",
        )
        summary = CanvasEvidencePipeline(sessions, Extractor((claim,))).process_pending()
        with sessions() as session:
            claim_id = session.scalar(select(Claim.id))

        assert summary.needs_review == 1
        assert ProfessorIdentityService(sessions).list_verified() == []
        confirmed = ProfessorIdentityService(sessions).confirm_claim(claim_id)
        assert confirmed["course_name"] == "Network Security"
        assert confirmed["sender"] == "p***@example.edu"
        assert len(ProfessorIdentityService(sessions).list_verified()) == 1
    finally:
        engine.dispose()


def test_browser_professor_routes_are_csrf_protected_and_never_return_raw_email(
    tmp_path: Path,
) -> None:
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'professor-api.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        create_schema(engine)
        session.add(Course(canvas_course_id="42", name="Network Security"))
        session.commit()
        course_id = session.scalar(select(Course.id))
    with TestClient(create_app(settings, engine=engine), base_url="https://due.test") as client:
        assert client.get("/api/v1/dashboard/professors").status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        path = "/api/v1/dashboard/professors"
        payload = {"course_id": course_id, "email": "professor@example.edu"}
        assert client.post(path, json=payload).status_code == 403
        created = client.post(
            path,
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json=payload,
        )
        listed = client.get(path)

    assert created.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["course_options"] == [
        {"id": course_id, "name": "Network Security"}
    ]
    assert listed.json()["items"][0]["sender"] == "p***@example.edu"
    assert "professor@example.edu" not in created.text.casefold() + listed.text.casefold()
    engine.dispose()
