from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.config.settings import DueSoonSettings


def build_client(tmp_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{(tmp_path / 'duesoon.db').as_posix()}",
        "environment": "test",
    }
    values.update(overrides)
    settings = DueSoonSettings(_env_file=None, **values)
    return TestClient(create_app(settings))


def test_liveness_endpoint(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "duesoon"}


def test_readiness_checks_database(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_system_info_contains_only_non_secret_metadata(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        api_token="api-secret",
        ntfy_token="ntfy-secret",
    ) as client:
        response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "service": "duesoon",
        "version": "0.1.0",
        "environment": "test",
        "dry_run": True,
        "scheduler_enabled": False,
        "notification_provider": "disabled",
    }
    assert "api-secret" not in response.text
    assert "ntfy-secret" not in response.text


def test_inherited_high_risk_routes_are_not_registered(tmp_path: Path) -> None:
    inherited_paths = ("/shell", "/chat", "/gallery", "/mcp", "/research", "/tts")

    with build_client(tmp_path) as client:
        statuses = {path: client.get(path).status_code for path in inherited_paths}

    assert statuses == {path: 404 for path in inherited_paths}


def test_readiness_fails_closed_when_database_is_unavailable(tmp_path: Path) -> None:
    class BrokenEngine:
        def connect(self):
            raise OSError("database unavailable")

        def dispose(self) -> None:
            pass

    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'unused.db').as_posix()}",
    )

    with TestClient(create_app(settings, engine=BrokenEngine())) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
