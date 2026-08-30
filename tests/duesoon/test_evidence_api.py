"""Evidence inspection and owner-confirmation API security tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    Course,
    SourceRecord,
    Submission,
)


ORIGIN = "https://due.test"
API_HEADERS = {"X-API-Token": "api-secret"}


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'evidence-api.db').as_posix()}",
        api_token="api-secret",
        web_enabled=True,
        public_origin=ORIGIN,
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    client = TestClient(create_app(settings, engine=engine), base_url=ORIGIN)
    return client, engine


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"username": "owner", "password": "correct-password-123"},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def seed_assignment(engine) -> tuple[int, datetime]:
    observed = datetime(2026, 8, 28, 12, tzinfo=UTC)
    canvas_due = observed + timedelta(days=3)
    with session_factory(engine)() as session:
        course = Course(canvas_course_id="42", name="Network Security")
        assignment = Assignment(
            canvas_assignment_id="99",
            course=course,
            canonical_title="Lab 4",
            canvas_due_at=canvas_due,
            canvas_updated_at=observed,
            points_possible=100,
            published=True,
            first_seen_at=observed,
            last_seen_at=observed,
        )
        session.add_all(
            [
                assignment,
                Submission(
                    assignment=assignment,
                    normalized_status="not_submitted",
                    missing=False,
                    late=False,
                    observed_at=observed,
                    raw_payload={"private_submission": "must-not-leak"},
                ),
            ]
        )
        session.flush()
        source = SourceRecord(
            source_system="canvas",
            source_type="inbox_message",
            external_id="unresolved-private-message",
            course_id=course.id,
            source_published_at=observed,
            observed_at=observed,
            content_hash="private-source-hash",
            raw_payload={"private_excerpt": "secret professor message"},
        )
        claim = Claim(
            source_record=source,
            claim_type="deadline_is",
            normalized_value={
                "due_at": (observed + timedelta(days=2)).isoformat(),
                "precision": "exact_datetime",
            },
            source_locator="Secret professor sentence must not leak.",
            author_identity="private-professor@example.test",
            author_role="instructor",
            source_published_at=observed,
            source_observed_at=observed,
            extraction_method="fixture",
            extractor_version="claims-v1",
            extraction_confidence=0.6,
            validation_status="validated",
            claim_fingerprint="private-claim-hash",
        )
        session.add(
            AssignmentEvidence(
                assignment=assignment,
                claim=claim,
                course_match_score=1.0,
                assignment_match_score=0.60,
                authority_score=1.0,
                explicitness_score=1.0,
                precision="exact_datetime",
                disposition="unresolved",
                explanation="Secret professor sentence must not leak.",
            )
        )
        session.commit()
        return assignment.id, canvas_due


def test_api_token_evidence_routes_confirm_idempotently_and_redact_sources(
    tmp_path: Path,
) -> None:
    client, engine = build(tmp_path)
    confirmed_due = datetime(2026, 8, 30, 18, 30, tzinfo=UTC)
    with client:
        assignment_id, canvas_due = seed_assignment(engine)

        assert client.get(f"/api/v1/assignments/{assignment_id}/evidence").status_code == 401
        assert client.post(
            f"/api/v1/assignments/{assignment_id}/confirm-deadline",
            json={"due_at": confirmed_due.isoformat()},
        ).status_code == 401
        initial = client.get(
            f"/api/v1/assignments/{assignment_id}/evidence", headers=API_HEADERS
        )
        naive = client.post(
            f"/api/v1/assignments/{assignment_id}/confirm-deadline",
            headers=API_HEADERS,
            json={"due_at": "2026-08-30T18:30:00"},
        )
        first = client.post(
            f"/api/v1/assignments/{assignment_id}/confirm-deadline",
            headers=API_HEADERS,
            json={"due_at": confirmed_due.isoformat()},
        )
        second = client.post(
            f"/api/v1/assignments/{assignment_id}/confirm-deadline",
            headers=API_HEADERS,
            json={"due_at": confirmed_due.isoformat()},
        )
        assignment = client.get(
            f"/api/v1/assignments/{assignment_id}", headers=API_HEADERS
        )

    assert initial.status_code == 200
    assert datetime.fromisoformat(initial.json()["effective_due_at"]) == canvas_due
    assert naive.status_code == 422
    assert naive.json()["detail"] == "deadline must include an explicit timezone offset"
    assert first.status_code == 200 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    assert first.json()["evidence_id"] == second.json()["evidence_id"]
    assert datetime.fromisoformat(first.json()["inspection"]["effective_due_at"]) == confirmed_due
    assert first.json()["inspection"]["deadline_confidence"] == "high"
    assert assignment.status_code == 200
    body = assignment.json()
    assert datetime.fromisoformat(body["effective_due_at"]) == confirmed_due
    assert datetime.fromisoformat(body["operational_due_at"]) == confirmed_due
    assert body["due_at_precision"] == "exact_datetime"
    assert body["deadline_evidence_ids"] == [first.json()["evidence_id"]]
    assert body["urgency"]["config_version"] == "urgency-v2"
    assert 0 <= body["urgency"]["total"] <= 100

    combined = initial.text + first.text + second.text + assignment.text
    for secret in (
        "must-not-leak",
        "secret professor message",
        "Secret professor sentence",
        "private-professor@example.test",
        "api-secret",
    ):
        assert secret not in combined

    with session_factory(engine)() as session:
        owner_sources = session.scalar(
            select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_system == "owner"
            )
        )
        owner_claims = session.scalar(
            select(func.count()).select_from(Claim).where(
                Claim.extraction_method == "owner_confirmation"
            )
        )
        owner_links = session.scalar(
            select(func.count()).select_from(AssignmentEvidence).where(
                AssignmentEvidence.owner_confirmed.is_(True)
            )
        )
        stored = session.scalar(
            select(AssignmentEvidence).where(AssignmentEvidence.owner_confirmed.is_(True))
        )
        assert owner_sources == owner_claims == owner_links == 1
        assert stored is not None
        assert stored.disposition == "admitted"
        assert stored.precision == "exact_datetime"
        assert stored.explanation.startswith("Owner confirmed")


def test_evidence_routes_return_404_for_unknown_assignment(tmp_path: Path) -> None:
    client, _engine = build(tmp_path)
    with client:
        get_response = client.get("/api/v1/assignments/999/evidence", headers=API_HEADERS)
        post_response = client.post(
            "/api/v1/assignments/999/confirm-deadline",
            headers=API_HEADERS,
            json={"due_at": "2026-08-30T18:30:00+00:00"},
        )

    assert get_response.status_code == 404
    assert post_response.status_code == 404


def test_browser_evidence_routes_require_session_and_csrf(tmp_path: Path) -> None:
    client, engine = build(tmp_path)
    due_at = datetime(2026, 8, 30, 18, 30, tzinfo=UTC)
    with client:
        assignment_id, _ = seed_assignment(engine)
        path = f"/api/v1/dashboard/assignments/{assignment_id}"
        assert client.get(f"{path}/evidence").status_code == 401

        csrf = login(client)
        inspected = client.get(f"{path}/evidence")
        no_csrf = client.post(
            f"{path}/confirm-deadline", json={"due_at": due_at.isoformat()}
        )
        confirmed = client.post(
            f"{path}/confirm-deadline",
            headers={"X-CSRF-Token": csrf},
            json={"due_at": due_at.isoformat()},
        )

    assert inspected.status_code == 200
    assert no_csrf.status_code == 403
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] is True
    assert confirmed.json()["inspection"]["assignment_id"] == assignment_id
    assert "private_excerpt" not in inspected.text + confirmed.text


def test_browser_owner_can_attach_sanitized_gmail_claim_to_assignment(
    tmp_path: Path,
) -> None:
    client, engine = build(tmp_path)
    observed = datetime(2026, 8, 28, 12, tzinfo=UTC)
    candidate_due = observed + timedelta(days=2)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="42", name="Network Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Midterm Test",
                canvas_due_at=None,
                published=True,
                first_seen_at=observed,
                last_seen_at=observed,
            )
            source = SourceRecord(
                source_system="gmail",
                source_type="message",
                external_id="gmail-midterm",
                course_id=None,
                source_published_at=observed,
                observed_at=observed,
                content_hash="gmail-midterm-hash",
                raw_payload={"body": "private professor email body"},
            )
            claim = Claim(
                source_record=source,
                claim_type="deadline_is",
                assignment_hint="Midterm Test",
                normalized_value={
                    "due_at": candidate_due.isoformat(),
                    "precision": "exact_datetime",
                },
                source_locator="private professor sentence",
                author_identity="professor@example.edu",
                author_role="email_sender_unverified",
                source_published_at=observed,
                source_observed_at=observed,
                extraction_method="fixture",
                extractor_version="claims-v1",
                extraction_confidence=0.95,
                validation_status="validated",
                claim_fingerprint="gmail-midterm-claim",
            )
            session.add_all([assignment, claim])
            session.commit()
            assignment_id, claim_id = assignment.id, claim.id

        csrf = login(client)
        path = f"/api/v1/dashboard/review/evidence/{claim_id}/confirm-assignment"
        assert client.post(path, json={"assignment_id": assignment_id}).status_code == 403
        review = client.get("/api/v1/dashboard/review")
        confirmed = client.post(
            path,
            headers={"X-CSRF-Token": csrf},
            json={"assignment_id": assignment_id},
        )

    assert review.status_code == 200
    assert review.json()["assignment_options"] == [
        {
            "id": assignment_id,
            "title": "Midterm Test",
            "course_name": "Network Security",
        }
    ]
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "admitted"
    combined = review.text + confirmed.text
    assert "private professor email body" not in combined
    assert "private professor sentence" not in combined
    assert "professor@example.edu" not in combined
