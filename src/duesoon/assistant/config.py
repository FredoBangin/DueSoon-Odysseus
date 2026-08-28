"""Secret-bearing model configuration loaded only from process environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_provider_base_url(value: str, *, require_https: bool = False) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    allowed = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed or not parsed.netloc:
        raise ValueError("model provider base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("model provider base URL cannot contain credentials, query, or fragment")
    return normalized


class ModelAssistantConfig(BaseSettings):
    """Provider secret plus bounded defaults; secret never enters database/API output."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DUESOON_MODEL_",
        extra="ignore",
    )

    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr | None = None
    primary_model: str | None = None
    fallback_models: str = ""
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    max_input_tokens: int = Field(default=6000, ge=256, le=32000)
    max_output_tokens: int = Field(default=700, ge=64, le=4000)
    call_budget: int = Field(default=2, ge=1, le=5)
    environment: Literal["development", "test", "production"] = "development"

    @model_validator(mode="after")
    def validate_provider(self) -> "ModelAssistantConfig":
        self.base_url = validate_provider_base_url(
            self.base_url, require_https=self.environment == "production"
        )
        if self.enabled and (self.api_key is None or not self.primary_model):
            raise ValueError("enabled model assistant requires API key and primary model")
        return self

    @property
    def ordered_fallbacks(self) -> tuple[str, ...]:
        values = (item.strip() for item in self.fallback_models.split(","))
        return tuple(dict.fromkeys(item for item in values if item and item != self.primary_model))


@dataclass(frozen=True)
class EffectiveModelSettings:
    enabled: bool
    base_url: str
    api_key: SecretStr | None
    primary_model: str | None
    fallback_models: tuple[str, ...]
    timeout_seconds: float
    max_input_tokens: int
    max_output_tokens: int
    call_budget: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key is not None and self.primary_model and self.base_url)
