"""Validated environment configuration for DueSoon."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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
    api_token: SecretStr | None = None

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

    @model_validator(mode="after")
    def validate_runtime_invariants(self) -> "DueSoonSettings":
        if (
            self.scheduler_enabled
            and self.database_url.startswith("sqlite")
            and self.scheduler_workers != 1
        ):
            raise ValueError("SQLite requires exactly one scheduler worker")

        if self.environment == "production" and self.api_token is None:
            raise ValueError("DUESOON_API_TOKEN is required in production")

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
