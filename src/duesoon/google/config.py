"""Server-only Google Workspace configuration."""

from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleWorkspaceConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DUESOON_GOOGLE_",
        extra="ignore",
    )

    enabled: bool = False
    gmail_enabled: bool = False
    calendar_enabled: bool = False
    client_id: SecretStr | None = None
    client_secret: SecretStr | None = None
    refresh_token: SecretStr | None = None
    timeout_seconds: float = Field(default=15.0, ge=1, le=60)
    sync_interval_seconds: int = Field(default=900, ge=300, le=86400)

    @model_validator(mode="after")
    def validate_credentials(self) -> "GoogleWorkspaceConfig":
        if self.enabled:
            missing = [
                name for name, value in (
                    ("CLIENT_ID", self.client_id),
                    ("CLIENT_SECRET", self.client_secret),
                    ("REFRESH_TOKEN", self.refresh_token),
                ) if value is None
            ]
            if missing:
                raise ValueError(
                    "Google Workspace requires DUESOON_GOOGLE_" +
                    ", DUESOON_GOOGLE_".join(missing)
                )
            if not self.gmail_enabled and not self.calendar_enabled:
                raise ValueError("Google Workspace requires at least one read-only adapter")
        return self

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)
