from __future__ import annotations

from datetime import UTC, datetime
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.discord import DiscordPublishError, DiscordWebhookPublisher


WEBHOOK = "https://discord.com/api/webhooks/123456789/fake-webhook-secret"
NOW = datetime(2026, 9, 28, 12, 30, tzinfo=UTC)


def settings(**values: object) -> DueSoonSettings:
    return DueSoonSettings(_env_file=None, environment="test", discord_enabled=True,
                           discord_webhook_url=WEBHOOK, **values)


def test_discord_embed_matches_log_style_and_confirms_message_without_mentions(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["wait"] == "true"
        payload = json.loads(request.content)
        assert payload["allowed_mentions"] == {"parse": []}
        assert payload["username"] == "DueSoon"
        embed = payload["embeds"][0]
        assert embed["author"]["name"] == "🖥️ DUESOON LOG"
        assert embed["color"] == 0xF39C12
        assert embed["timestamp"] == NOW.isoformat()
        assert embed["description"].startswith("```text\n 1 [2026-09-28 08:30:00 EDT] DueSoon briefing")
        assert "Mon, Sep 28 at 11:59 PM EDT" in embed["description"]
        assert embed["description"].count("```") == 2
        return httpx.Response(200, json={"id": "discord-message-1"})

    publisher = DiscordWebhookPublisher(
        settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: NOW,
    )
    with caplog.at_level(logging.INFO, logger="httpx"):
        result = publisher.publish(title="DueSoon briefing", message="Sample lab — Mon, Sep 28 at 11:59 PM EDT\n``` @everyone")
    assert result.provider_message_id == "discord-message-1"
    assert "fake-webhook-secret" not in caplog.text
    assert "[Discord webhook redacted]" in caplog.text


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/123/token", "https://example.com/api/webhooks/123/token",
    "https://discord.com.evil.test/api/webhooks/123/token", "https://discord.com/api/webhooks/123/token?x=secret",
    "https://user@discord.com/api/webhooks/123/token", "https://discord.com/api/webhooks/123/token#fragment",
])
def test_discord_config_rejects_non_webhook_destinations_without_leaking_input(url: str) -> None:
    with pytest.raises(ValidationError) as error:
        DueSoonSettings(_env_file=None, environment="test", discord_enabled=True, discord_webhook_url=url)
    assert url not in str(error.value)


@pytest.mark.parametrize(("status", "retryable", "ambiguous"), [(403, False, False), (404, False, False), (500, False, True), (429, True, False)])
def test_discord_provider_failures_are_classified_and_redacted(status, retryable, ambiguous) -> None:
    publisher = DiscordWebhookPublisher(settings(), client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={"retry_after": 90, "private": str(request.url)})
    )))
    with pytest.raises(DiscordPublishError) as error:
        publisher.publish(title="Sample", message="Sample")
    assert error.value.retryable is retryable
    assert error.value.ambiguous is ambiguous
    assert "fake-webhook-secret" not in str(error.value)
    if status == 429:
        assert error.value.retry_after == 90


def test_discord_timeout_or_unconfirmed_response_is_not_blindly_retried() -> None:
    def timeout(request):
        raise httpx.ReadTimeout("private " + str(request.url), request=request)
    for handler in (timeout, lambda request: httpx.Response(204)):
        publisher = DiscordWebhookPublisher(settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))
        with pytest.raises(DiscordPublishError) as error:
            publisher.publish(title="Sample", message="Sample")
        assert error.value.ambiguous is True
        assert error.value.retryable is False
        assert error.value.__suppress_context__ or error.value.__context__ is None
