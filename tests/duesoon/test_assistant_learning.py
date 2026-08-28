from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.assistant.config import EffectiveModelSettings
from src.duesoon.assistant.provider import OpenAICompatibleProvider
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings


def test_model_router_uses_backup_only_after_transient_failure() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        selected = json.loads(request.content)["model"]
        models.append(selected)
        if selected == "primary":
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": (
            '{"answer":"Backup worked","confidence":"likely",'
            '"evidence_ids":["assignment:1"]}'
        )}}]})

    provider = OpenAICompatibleProvider(
        lambda timeout: httpx.Client(
            timeout=timeout, transport=httpx.MockTransport(handler)
        )
    )
    answer = provider.complete(
        EffectiveModelSettings(
            enabled=True,
            base_url="https://models.example/v1",
            api_key=SecretStr("not-returned"),
            primary_model="primary",
            fallback_models=("backup",),
            timeout_seconds=3,
            max_input_tokens=1000,
            max_output_tokens=100,
            call_budget=2,
        ),
        [{"role": "user", "content": "What is due?"}],
    )
    assert models == ["primary", "backup"]
    assert answer.model == "backup"
    assert answer.calls_used == 2


def test_feedback_requires_explanation_and_review_is_reversible(tmp_path: Path) -> None:
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'learning.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    client = TestClient(create_app(settings, engine=engine), base_url="https://due.test")
    with client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        answer = client.post(
            "/api/v1/dashboard/assistant",
            headers=headers,
            json={"question": "Any updates?"},
        ).json()

        incomplete = client.post(
            f"/api/v1/dashboard/assistant/{answer['answer_id']}/feedback",
            headers=headers,
            json={"verdict": "uncertain"},
        )
        assert incomplete.status_code == 200
        assert incomplete.json()["needs_correction"] is True

        corrected = client.post(
            f"/api/v1/dashboard/assistant/{answer['answer_id']}/feedback",
            headers=headers,
            json={
                "verdict": "incorrect",
                "what_was_wrong": "State when Canvas was last synchronized.",
                "scope_type": "global",
            },
        )
        proposal = corrected.json()["proposal"]
        assert proposal["status"] == "proposed"
        assert "Cannot alter deadlines" in proposal["affected_future_behavior"]

        assert client.post(
            f"/api/v1/dashboard/review/{proposal['id']}",
            json={"action": "approve"},
        ).status_code == 403
        approved = client.post(
            f"/api/v1/dashboard/review/{proposal['id']}",
            headers=headers,
            json={"action": "approve"},
        )
        assert approved.json()["status"] == "approved"
        reverted = client.post(
            f"/api/v1/dashboard/review/{proposal['id']}",
            headers=headers,
            json={"action": "undo", "reason": "Wrong scope"},
        )
        assert reverted.json()["status"] == "reverted"
