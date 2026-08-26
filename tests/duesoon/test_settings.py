from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.duesoon.config.settings import DueSoonSettings


DUESOON_ENV_VARS = (
    "DUESOON_ENV",
    "DUESOON_DATABASE_URL",
    "DUESOON_DRY_RUN",
    "DUESOON_SCHEDULER_ENABLED",
    "DUESOON_SCHEDULER_WORKERS",
    "DUESOON_API_TOKEN",
    "DUESOON_NTFY_ENABLED",
    "DUESOON_NTFY_URL",
    "DUESOON_NTFY_TOPIC",
    "DUESOON_NTFY_TOKEN",
)


@pytest.fixture(autouse=True)
def clean_duesoon_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in DUESOON_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_safe_defaults_are_dry_run_and_single_worker() -> None:
    settings = DueSoonSettings(_env_file=None)

    assert settings.environment == "development"
    assert settings.database_url == "sqlite:///./data/duesoon.db"
    assert settings.dry_run is True
    assert settings.scheduler_enabled is False
    assert settings.scheduler_workers == 1
    assert settings.ntfy_enabled is False


def test_environment_values_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUESOON_ENV", "production")
    monkeypatch.setenv("DUESOON_DRY_RUN", "false")
    monkeypatch.setenv("DUESOON_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DUESOON_API_TOKEN", "test-api-token")

    settings = DueSoonSettings(_env_file=None)

    assert settings.environment == "production"
    assert settings.dry_run is False
    assert settings.scheduler_enabled is True
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "test-api-token"


def test_sqlite_scheduler_rejects_multiple_workers() -> None:
    with pytest.raises(ValidationError, match="exactly one scheduler worker"):
        DueSoonSettings(
            _env_file=None,
            scheduler_enabled=True,
            scheduler_workers=2,
        )


def test_production_requires_api_token() -> None:
    with pytest.raises(ValidationError, match="DUESOON_API_TOKEN"):
        DueSoonSettings(_env_file=None, environment="production")


def test_enabled_ntfy_requires_private_delivery_settings() -> None:
    with pytest.raises(ValidationError, match="DUESOON_NTFY_URL"):
        DueSoonSettings(_env_file=None, ntfy_enabled=True)


def test_production_ntfy_requires_https() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        DueSoonSettings(
            _env_file=None,
            environment="production",
            api_token="api-secret",
            ntfy_enabled=True,
            ntfy_url="http://ntfy:80",
            ntfy_topic="student-topic",
            ntfy_token="ntfy-secret",
        )


def test_secret_values_are_redacted_from_repr() -> None:
    settings = DueSoonSettings(
        _env_file=None,
        api_token="api-secret",
        ntfy_token="ntfy-secret",
    )

    rendered = repr(settings)
    assert "api-secret" not in rendered
    assert "ntfy-secret" not in rendered
