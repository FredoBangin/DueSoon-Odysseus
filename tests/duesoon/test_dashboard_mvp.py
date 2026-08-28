from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password, verify_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import Assignment, Course, Submission


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


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-password-123")
    assert verify_password("correct-password-123", encoded)
    assert not verify_password("wrong-password-123", encoded)


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
            session.add_all([course, assignment, Submission(assignment=assignment,
                normalized_status="not_submitted", missing=False, late=False,
                observed_at=now, raw_payload={"secret": "not-returned"})])
            session.commit()
        assert client.get("/api/v1/dashboard/briefing").status_code == 401
        csrf = login(client)
        briefing = client.get("/api/v1/dashboard/briefing")
        assert briefing.status_code == 200
        assert briefing.json()["upcoming"][0]["effective_due_at"]
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
