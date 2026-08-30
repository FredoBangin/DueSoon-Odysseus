"""Authenticated ntfy JSON publisher."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.duesoon.config.settings import DueSoonSettings


class NtfyPublishError(RuntimeError):
    """Sanitized provider error safe to expose through the API."""

    def __init__(
        self,
        message: str,
        *,
        ambiguous: bool = False,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous
        self.retryable = retryable


@dataclass(frozen=True)
class PublishResult:
    provider_message_id: str | None


class NtfyPublisher:
    """Publish concise notifications without leaking provider secrets."""

    def __init__(
        self,
        settings: DueSoonSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.ntfy_enabled:
            raise ValueError("ntfy delivery is disabled")
        if settings.ntfy_url is None or settings.ntfy_topic is None or settings.ntfy_token is None:
            raise ValueError("ntfy delivery settings are incomplete")

        self._url = f"{settings.ntfy_url.rstrip('/')}/"
        self._topic = settings.ntfy_topic.get_secret_value()
        self._token = settings.ntfy_token.get_secret_value()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.ntfy_timeout_seconds,
            follow_redirects=False,
        )

    def publish(
        self,
        *,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> PublishResult:
        payload: dict[str, object] = {
            "topic": self._topic,
            "title": title,
            "message": message,
            "priority": priority,
        }
        if tags:
            payload["tags"] = tags

        try:
            response = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise NtfyPublishError(
                "ntfy request timed out; delivery outcome is unknown",
                ambiguous=True,
            ) from exc
        except httpx.ConnectError as exc:
            raise NtfyPublishError(
                "ntfy connection failed before delivery",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise NtfyPublishError(
                "ntfy request failed; delivery outcome is unknown",
                ambiguous=True,
            ) from exc

        if not response.is_success:
            if response.status_code == 429:
                raise NtfyPublishError(
                    "ntfy rejected request with status 429",
                    retryable=True,
                )
            raise NtfyPublishError(
                f"ntfy rejected request with status {response.status_code}",
                ambiguous=response.status_code >= 500,
            )

        try:
            provider_id = response.json().get("id")
        except (ValueError, AttributeError):
            provider_id = None
        return PublishResult(
            provider_message_id=str(provider_id) if provider_id is not None else None
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
