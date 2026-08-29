from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings


class FakeGoogle:
    config = SimpleNamespace(gmail_enabled=True, calendar_enabled=False)

    def list_gmail_messages(self, *, query: str, limit: int):
        assert query == "label:inbox newer_than:90d"
        assert limit == 25
        return [{
            "id": "message-1",
            "thread_id": "thread-1",
            "subject": "Lab deadline moved",
            "from": "Professor <professor@example.edu>",
            "date": "Fri, 28 Aug 2026 12:30:00 -0400",
            "snippet": "The lab is due Monday.",
            "body": "Private academic evidence: the lab is due Monday.",
            "attachments": [{
                "filename": "rubric.pdf",
                "mime_type": "application/pdf",
                "attachment_id": "server-only-id",
            }],
        }]


class RecordingExtractor:
    def __init__(self) -> None:
        self.calls = []

    def extract(self, source):
        self.calls.append(source)
        return ()


def test_gmail_sync_is_csrf_protected_idempotent_and_visible_as_sanitized_evidence(
    tmp_path: Path,
) -> None:
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'gmail.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    app = create_app(settings, engine=engine, google_client=FakeGoogle())
    with TestClient(app, base_url="https://due.test") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}

        assert client.post("/api/v1/dashboard/gmail/sync").status_code == 403
        first = client.post("/api/v1/dashboard/gmail/sync", headers=csrf)
        second = client.post("/api/v1/dashboard/gmail/sync", headers=csrf)
        assert first.json() == {"stored": 1, "unchanged": 0}
        assert second.json() == {"stored": 0, "unchanged": 1}

        documents = client.get("/api/v1/dashboard/documents")
        assert documents.status_code == 200
        item = documents.json()["items"][0]
        assert item["source"] == "gmail"
        assert item["source_type"] == "message"
        assert item["title"] == "Lab deadline moved"
        assert item["sender"] == "Professor <professor@example.edu>"
        assert "Private academic evidence" not in documents.text
        assert "server-only-id" not in documents.text


def test_gmail_sync_triggers_bounded_evidence_processing_when_model_is_available(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DUESOON_MODEL_ENABLED", "true")
    monkeypatch.setenv("DUESOON_MODEL_API_KEY", "test-only-key")
    monkeypatch.setenv("DUESOON_MODEL_PRIMARY_MODEL", "primary")
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'gmail-pipeline.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    extractor = RecordingExtractor()
    app = create_app(
        settings,
        engine=engine,
        google_client=FakeGoogle(),
        claim_extractor=extractor,
    )
    with TestClient(app, base_url="https://due.test") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        response = client.post(
            "/api/v1/dashboard/gmail/sync",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
        )

    assert response.json() == {"stored": 1, "unchanged": 0}
    assert len(extractor.calls) == 1
    assert extractor.calls[0].source_type == "message"
    assert "Private academic evidence" in extractor.calls[0].text
