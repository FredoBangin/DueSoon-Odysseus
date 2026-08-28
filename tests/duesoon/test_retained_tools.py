from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import Assignment, Course, SourceRecord


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'retained.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    client = TestClient(create_app(settings, engine=engine), base_url="https://due.test")
    return client, engine


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://due.test"},
        json={"username": "owner", "password": "correct-password-123"},
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_notes_and_memory_are_owner_controlled_and_do_not_change_assignment(tmp_path: Path) -> None:
    client, engine = build(tmp_path)
    due_at = datetime.now(UTC) + timedelta(days=2)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="course-1", name="Biology")
            assignment = Assignment(
                canvas_assignment_id="assignment-1",
                course=course,
                canonical_title="Lab report",
                canvas_due_at=due_at,
                published=True,
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
            )
            session.add(assignment)
            session.commit()
            assignment_id, course_id = assignment.id, course.id

        headers = login(client)
        assert client.post(
            "/api/v1/dashboard/notes", json={"title": "Plan", "body": "Draft methods"}
        ).status_code == 403
        note = client.post(
            "/api/v1/dashboard/notes",
            headers=headers,
            json={
                "title": "Plan",
                "body": "Draft methods",
                "assignment_id": assignment_id,
                "course_id": course_id,
            },
        )
        assert note.status_code == 200
        assert note.json()["assignment_title"] == "Lab report"
        assert client.get("/api/v1/dashboard/notes").json()["items"][0]["body"] == "Draft methods"
        archived = client.patch(
            f"/api/v1/dashboard/notes/{note.json()['id']}",
            headers=headers,
            json={"archived": True},
        )
        assert archived.json()["archived"] is True
        assert client.get("/api/v1/dashboard/notes").json()["items"] == []

        invalid = client.post(
            "/api/v1/dashboard/memories",
            headers=headers,
            json={
                "memory_type": "deadline_override",
                "scope_type": "global",
                "label": "Unsafe",
                "value": "Change deadline",
            },
        )
        assert invalid.status_code == 422
        memory = client.post(
            "/api/v1/dashboard/memories",
            headers=headers,
            json={
                "memory_type": "alias",
                "scope_type": "course",
                "scope_ref": "Biology",
                "label": "BIO",
                "value": "BIO means Biology",
            },
        )
        assert memory.status_code == 200
        assert memory.json()["created_by"] == "owner"
        disabled = client.patch(
            f"/api/v1/dashboard/memories/{memory.json()['id']}",
            headers=headers,
            json={"active": False},
        )
        assert disabled.json()["active"] is False

        with session_factory(engine)() as session:
            assignment = session.get(Assignment, assignment_id)
            assert assignment is not None
            assert assignment.canonical_title == "Lab report"
            assert assignment.canvas_due_at.replace(tzinfo=UTC) == due_at


def test_documents_are_read_only_sanitized_canvas_metadata(tmp_path: Path) -> None:
    client, engine = build(tmp_path)
    now = datetime.now(UTC)
    secret_url = "https://canvas.example/download?signed=super-secret"
    secret_body = "professor-only raw evidence body"
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="course-2", name="Chemistry")
            session.add(course)
            session.flush()
            session.add_all([
                SourceRecord(
                    source_system="canvas",
                    source_type="file",
                    external_id="file-1",
                    course_id=course.id,
                    observed_at=now,
                    content_hash="a" * 64,
                    version=1,
                    raw_payload={
                        "display_name": "Syllabus.pdf",
                        "content-type": "application/pdf",
                        "size": 2048,
                        "url": secret_url,
                        "body": secret_body,
                    },
                ),
                SourceRecord(
                    source_system="canvas",
                    source_type="announcement",
                    external_id="announcement-1",
                    course_id=course.id,
                    observed_at=now,
                    content_hash="b" * 64,
                    version=1,
                    raw_payload={"title": "Not a document"},
                ),
            ])
            session.commit()

        login(client)
        response = client.get("/api/v1/dashboard/documents")
        assert response.status_code == 200
        payload = response.json()
        assert payload["access"] == "read_only"
        assert len(payload["items"]) == 1
        assert payload["items"][0]["title"] == "Syllabus.pdf"
        assert payload["items"][0]["course_name"] == "Chemistry"
        assert secret_url not in response.text
        assert secret_body not in response.text


def test_retained_views_are_reported_live(tmp_path: Path) -> None:
    client, _engine = build(tmp_path)
    with client:
        login(client)
        features = client.get("/api/v1/dashboard/settings").json()["features"]
        assert features["notes"] == "enabled"
        assert features["memory"] == "owner-controlled"
        assert features["documents"] == "read-only"
