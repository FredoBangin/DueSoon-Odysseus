from __future__ import annotations

from datetime import UTC, datetime
import logging
import math
import re
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import PublishResult


class DiscordPublishError(RuntimeError):
    def __init__(
        self, message: str, *, ambiguous: bool = False,
        retryable: bool = False, retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous
        self.retryable = retryable
        self.retry_after = retry_after


class _WebhookRedaction(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = re.sub(
            r"(?:https://discord\.com)?/api/(?:v\d+/)?webhooks/[^\s\"'<>]+",
            "[Discord webhook redacted]", message,
        )
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


for _name in ("httpx", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_name).addFilter(_WebhookRedaction())


def _log_text(value: str) -> str:
    return "".join(char for char in value if char in "\n\t" or ord(char) >= 32).replace("`", "ˋ")


def _description(value: str) -> str:
    headings = {"Due Today", "Due This Week", "Due Later", "Deadline changes", "Recently completed", "Course updates", "What changed", "Why it matters", "Next step", "Information needed", "Planning review"}
    return "\n".join(
        f"**{line}**" if line in headings else re.sub(r"([\\*_~|\[\]<>#])", r"\\\1", _log_text(line))
        for line in value.splitlines()
    )


class DiscordWebhookPublisher:
    def __init__(
        self, settings: DueSoonSettings, *, client: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not settings.discord_enabled or settings.discord_webhook_url is None:
            raise ValueError("Discord delivery is disabled or incomplete")
        self._url = settings.discord_webhook_url.get_secret_value()
        self._timezone = ZoneInfo(settings.timezone)
        self._clock = clock
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=settings.discord_timeout_seconds, follow_redirects=False,
        )

    def publish(self, *, title: str, message: str, priority: int = 3, **_unused: object) -> PublishResult:
        now = self._clock().astimezone(UTC)
        description = _description(message)
        if len(description) > 4096:
            raise DiscordPublishError("Discord embed exceeds the description limit")
        payload = {
            "username": "Bob, From DueSoon",
            "allowed_mentions": {"parse": []},
            "embeds": [{
                "title": _log_text(title)[:256],
                "description": description,
                "color": 0xF39C12,
                "timestamp": now.isoformat(),
                "footer": {"text": f"Updated {now.astimezone(self._timezone).strftime('%A, %B %d, %Y at %I:%M %p %Z')}"},
            }],
        }
        try:
            response = self._client.post(self._url, params={"wait": "true"}, json=payload)
        except httpx.ConnectError:
            raise DiscordPublishError("Discord connection failed before delivery", retryable=True) from None
        except httpx.RequestError:
            raise DiscordPublishError("Discord delivery outcome is unknown", ambiguous=True) from None
        if response.status_code == 429:
            try:
                delay = float(response.json().get("retry_after", 30))
                delay = delay if math.isfinite(delay) and delay >= 0 else 30
            except (ValueError, TypeError, AttributeError):
                delay = 30
            raise DiscordPublishError("Discord rate limited delivery", retryable=True, retry_after=delay)
        if not response.is_success:
            raise DiscordPublishError(
                f"Discord rejected delivery with status {response.status_code}",
                ambiguous=response.status_code >= 500,
            )
        try:
            message_id = response.json().get("id")
        except (ValueError, AttributeError):
            message_id = None
        if not message_id:
            raise DiscordPublishError("Discord did not confirm a message ID", ambiguous=True)
        return PublishResult(provider_message_id=str(message_id))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
