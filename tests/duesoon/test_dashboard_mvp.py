from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password, verify_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    AssignmentSnapshot,
    Claim,
    Course,
    SourceRecord,
    Submission,
    SyncRun,
)


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None, environment="test",
        database_url=f"sqlite:///{(tmp_path / 'web.db').as_posix()}",
        web_enabled=True, public_origin="https://due.test",
        owner_username="owner", owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    return TestClient(create_app(settings, engine=engine), base_url="https://due.test"), engine


def login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", headers={"Origin": "https://due.test"},
                           json={"username": "owner", "password": "correct-password-123"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    return response.json()["csrf_token"]


def attach_deadline_evidence(
    session,
    assignment: Assignment,
    *,
    external_id: str,
    due_at: datetime,
    source_type: str,
    claim_type: str = "deadline_is",
    published_at: datetime,
    authority: float,
) -> None:
    source = SourceRecord(
        source_system="canvas",
        source_type=source_type,
        external_id=external_id,
        content_hash=f"hash-{external_id}",
        source_published_at=published_at,
        observed_at=published_at,
        raw_payload={"private_message": "not-returned"},
    )
    claim = Claim(
        source_record=source,
        claim_type=claim_type,
        normalized_value={
            "due_at": due_at.isoformat(),
            "precision": "exact_datetime",
        },
        source_published_at=published_at,
        source_observed_at=published_at,
        extraction_method="deterministic_fixture",
        extractor_version="claims-v1",
        extraction_confidence=0.98,
        validation_status="validated",
        claim_fingerprint=f"claim-{external_id}",
    )
    session.add(
        AssignmentEvidence(
            assignment=assignment,
            claim=claim,
            course_match_score=1.0,
            assignment_match_score=1.0,
            authority_score=authority,
            explicitness_score=1.0,
            precision="exact_datetime",
            disposition="admitted",
            explanation="Validated fixture evidence.",
        )
    )


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-password-123")
    assert verify_password("correct-password-123", encoded)
    assert not verify_password("wrong-password-123", encoded)


def test_login_clears_the_retired_ntfy_web_service_worker(tmp_path: Path) -> None:
    client, _engine = build(tmp_path)
    with client:
        response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["clear-site-data"] == '"cache", "storage"'


def test_login_session_csrf_and_logout(tmp_path: Path) -> None:
    client, _engine = build(tmp_path)
    with client:
        assert client.get("/app").status_code == 200 or client.get("/app").history
        csrf = login(client)
        assert client.get("/api/v1/auth/session").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 403
        assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/v1/auth/session").status_code == 401


def test_dashboard_uses_real_canvas_records_and_is_browser_guarded(tmp_path: Path) -> None:
    client, engine = build(tmp_path)
    now = datetime.now(UTC)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="42", name="Security")
            assignment = Assignment(canvas_assignment_id="99", course=course,
                                    canonical_title="Lab 4", canvas_due_at=now + timedelta(hours=5),
                                    points_possible=100, html_url="https://canvas.example/99",
                                    published=True, first_seen_at=now, last_seen_at=now)
            source = SourceRecord(
                source_system="canvas", source_type="assignment", external_id="99",
                content_hash="assignment-source", observed_at=now,
                raw_payload={"private_content": "not-returned"},
            )
            session.add_all([course, assignment, source, Submission(assignment=assignment,
                normalized_status="not_submitted", missing=False, late=False,
                observed_at=now, raw_payload={"secret": "not-returned"}),
                SyncRun(source_system="canvas", status="completed", started_at=now,
                        finished_at=now, courses_seen=1, assignments_seen=1,
                        submissions_seen=1, source_versions_created=1)])
            session.flush()
            assignment.snapshots.extend([
                AssignmentSnapshot(
                    source_record_id=source.id, content_hash="previous-deadline",
                    normalized_payload={"due_at": (now + timedelta(hours=10)).isoformat()},
                    due_at=now + timedelta(hours=10), observed_at=now - timedelta(hours=1),
                ),
                AssignmentSnapshot(
                    source_record_id=source.id, content_hash="current-deadline",
                    normalized_payload={"due_at": (now + timedelta(hours=5)).isoformat()},
                    due_at=now + timedelta(hours=5), observed_at=now,
                ),
            ])
            session.commit()
        assert client.get("/api/v1/dashboard/briefing").status_code == 401
        csrf = login(client)
        briefing = client.get("/api/v1/dashboard/briefing")
        assert briefing.status_code == 200
        assert briefing.json()["freshness"]["canvas_status"] == "fresh"
        upcoming = briefing.json()["upcoming"][0]
        assert upcoming["effective_due_at"]
        assert upcoming["deadline_evidence_ids"] == ["canvas-assignment:99:current"]
        assert upcoming["due_at_precision"] == "exact_datetime"
        assert upcoming["deadline_resolution_explanation"]
        assert upcoming["conflicting_due_at"] == []
        change = briefing.json()["deadline_changes"][0]
        assert change["assignment_id"] == assignment.id
        assert change["direction"] == "earlier"
        assert change["difference_hours"] == 5.0
        assert "not-returned" not in briefing.text
        calendar = client.get(f"/api/v1/dashboard/calendar?start={now.date()}&end={(now + timedelta(days=2)).date()}")
        assert calendar.json()["events"][0]["read_only"] is True
        answer = client.post("/api/v1/dashboard/assistant", headers={"X-CSRF-Token": csrf},
                             json={"question": "What is due next?"})
        assert answer.json()["mode"] == "deterministic"


def test_web_assets_have_approved_tabs_and_no_browser_secret_storage(tmp_path: Path) -> None:
    client, _engine = build(tmp_path)
    with client:
        login(client)
        html = client.get("/app").text
        for label in ("Home", "Assistant", "Calendar", "Email", "Notifications", "Review", "Settings"):
            assert f">{label}<" in html
    root = Path(__file__).resolve().parents[2] / "src/duesoon/web/static/js"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
    assert "localStorage" not in source and "sessionStorage" not in source
    assert "X-API-Token" not in source and "serviceWorker" not in source


def test_dashboard_serves_inherited_odysseus_presentation_without_legacy_runtime(
    tmp_path: Path,
) -> None:
    client, _engine = build(tmp_path)
    with client:
        style = client.get("/static/style.css")
        assert style.status_code == 200
        assert "Odysseus UI — Consolidated Stylesheet" in style.text

        login(client)
        shell = client.get("/app")
        assert shell.status_code == 200
        assert 'href="/static/style.css"' in shell.text
        assert 'id="icon-rail"' in shell.text
        assert 'id="sidebar-user-bar"' in shell.text
        assert 'src="/static/app.js"' not in shell.text
        assert 'src="/static/sw.js"' not in shell.text


def test_briefing_uses_persisted_professor_correction_without_exposing_content(
    tmp_path: Path,
) -> None:
    client, engine = build(tmp_path)
    now = datetime.now(UTC)
    canvas_due = now + timedelta(days=2)
    corrected_due = now + timedelta(hours=5)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="42", name="Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Lab 4",
                canvas_due_at=canvas_due,
                canvas_updated_at=now - timedelta(days=2),
                published=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(assignment)
            attach_deadline_evidence(
                session,
                assignment,
                external_id="inbox-7",
                due_at=corrected_due,
                source_type="inbox_message",
                claim_type="deadline_moved_earlier_to",
                published_at=now - timedelta(hours=1),
                authority=1.0,
            )
            session.commit()

        login(client)
        response = client.get("/api/v1/dashboard/briefing")
        item = response.json()["upcoming"][0]

        assert response.status_code == 200
        assert datetime.fromisoformat(item["effective_due_at"]) == corrected_due
        assert datetime.fromisoformat(item["due_at"]) == corrected_due
        assert item["deadline_source_summary"] == "Resolved from canvas_inbox_correction"
        assert item["deadline_evidence_ids"] == ["assignment-evidence:1:claim:1"]
        assert response.json()["limitations"] == []
        assert "not-returned" not in response.text


def test_briefing_exposes_earliest_operational_date_for_persisted_conflict(
    tmp_path: Path,
) -> None:
    client, engine = build(tmp_path)
    now = datetime.now(UTC)
    earlier = now + timedelta(hours=8)
    later = now + timedelta(hours=20)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="42", name="Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Lab 4",
                published=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(assignment)
            attach_deadline_evidence(
                session,
                assignment,
                external_id="announcement-1",
                due_at=later,
                source_type="announcement",
                published_at=now - timedelta(hours=2),
                authority=0.97,
            )
            attach_deadline_evidence(
                session,
                assignment,
                external_id="inbox-1",
                due_at=earlier,
                source_type="inbox_message",
                published_at=now - timedelta(hours=1),
                authority=1.0,
            )
            session.commit()

        login(client)
        response = client.get("/api/v1/dashboard/briefing")
        item = response.json()["upcoming"][0]

        assert item["deadline_status"] == "conflicted"
        assert datetime.fromisoformat(item["due_at"]) == earlier
        assert set(map(datetime.fromisoformat, item["conflicting_due_at"])) == {
            earlier,
            later,
        }
        assert "private_message" not in response.text
