"""Validated environment configuration for DueSoon."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DueSoonSettings(BaseSettings):
    """Runtime settings with safe dry-run defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DUESOON_",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="DUESOON_ENV",
    )
    database_url: str = "sqlite:///./data/duesoon.db"
    dry_run: bool = True
    scheduler_enabled: bool = False
    scheduler_workers: int = Field(default=1, ge=1)
    scheduler_interval_seconds: int = Field(default=300, ge=30, le=3600)
    daily_digest_enabled: bool = True
    daily_digest_hour: int = Field(default=8, ge=0, le=23)
    daily_digest_max_items: int = Field(default=5, ge=1, le=10)
    evidence_retry_seconds: int = Field(default=3600, ge=900, le=86400)
    api_token: SecretStr | None = None

    web_enabled: bool = False
    public_origin: str | None = None
    owner_username: str = "duesoon-owner"
    owner_password_hash: SecretStr | None = None
    timezone: str = "America/New_York"
    session_cookie_name: str = "duesoon_session"
    session_ttl_minutes: int = Field(default=480, ge=15, le=10080)
    login_max_attempts: int = Field(default=5, ge=3, le=20)
    login_window_seconds: int = Field(default=900, ge=60, le=3600)

    ntfy_enabled: bool = False
    ntfy_url: str | None = None
    ntfy_topic: SecretStr | None = None
    ntfy_token: SecretStr | None = None
    ntfy_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    canvas_enabled: bool = False
    canvas_base_url: str | None = None
    canvas_access_token: SecretStr | None = None
    canvas_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    canvas_max_attempts: int = Field(default=3, ge=1, le=5)
    canvas_file_max_bytes: int = Field(default=8_000_000, ge=1024, le=25_000_000)

    @model_validator(mode="after")
    def validate_runtime_invariants(self) -> "DueSoonSettings":
        if (
            self.scheduler_enabled
            and self.database_url.startswith("sqlite")
            and self.scheduler_workers != 1
        ):
            raise ValueError("SQLite requires exactly one scheduler worker")

        if self.scheduler_enabled and not self.canvas_enabled:
            raise ValueError("scheduler requires Canvas ingestion")

        if self.scheduler_enabled and not self.dry_run and not self.ntfy_enabled:
            raise ValueError("live scheduler requires ntfy delivery")

        if self.environment == "production" and self.api_token is None:
            raise ValueError("DUESOON_API_TOKEN is required in production")

        if not self.timezone or any(character.isspace() for character in self.timezone):
            raise ValueError("DUESOON_TIMEZONE must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "DUESOON_TIMEZONE must name an available IANA timezone"
            ) from exc

        if self.public_origin:
            self.public_origin = self.public_origin.rstrip("/")
        if self.environment == "production" and self.web_enabled:
            if self.owner_password_hash is None or not self.public_origin:
                raise ValueError(
                    "web login requires DUESOON_OWNER_PASSWORD_HASH and DUESOON_PUBLIC_ORIGIN"
                )
            if not self.public_origin.startswith("https://"):
                raise ValueError("production web login requires an HTTPS public origin")

        if self.ntfy_enabled:
            missing = []
            if not self.ntfy_url:
                missing.append("DUESOON_NTFY_URL")
            if self.ntfy_topic is None:
                missing.append("DUESOON_NTFY_TOPIC")
            if self.ntfy_token is None:
                missing.append("DUESOON_NTFY_TOKEN")
            if missing:
                raise ValueError(f"ntfy delivery requires {', '.join(missing)}")
            if self.environment == "production" and not self.ntfy_url.startswith("https://"):
                raise ValueError("production ntfy delivery requires HTTPS")

        if self.canvas_base_url:
            self.canvas_base_url = self.canvas_base_url.rstrip("/")

        if self.canvas_enabled:
            missing = []
            if not self.canvas_base_url:
                missing.append("DUESOON_CANVAS_BASE_URL")
            if self.canvas_access_token is None:
                missing.append("DUESOON_CANVAS_ACCESS_TOKEN")
            if missing:
                raise ValueError(f"Canvas ingestion requires {', '.join(missing)}")
            if self.environment == "production" and not self.canvas_base_url.startswith(
                "https://"
            ):
                raise ValueError("production Canvas requires HTTPS")

        return self


@lru_cache(maxsize=1)
def get_settings() -> DueSoonSettings:
    """Load and cache process settings."""

    return DueSoonSettings()
