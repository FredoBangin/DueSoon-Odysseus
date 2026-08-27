from __future__ import annotations

import json

import httpx
import pytest

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import NtfyPublishError, NtfyPublisher


def build_settings() -> DueSoonSettings:
    return DueSoonSettings(
        _env_file=None,
        environment="test",
        dry_run=False,
        ntfy_enabled=True,
        ntfy_url="https://notify.example.test",
        ntfy_topic="private-student-topic",
        ntfy_token="ntfy-secret-token",
    )


def test_publish_uses_json_root_endpoint_and_bearer_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://notify.example.test/")
        assert request.headers["Authorization"] == "Bearer ntfy-secret-token"
        assert json.loads(request.content) == {
            "topic": "private-student-topic",
            "title": "DueSoon is live",
            "message": "Azure delivery reached ntfy.",
            "priority": 4,
            "tags": ["white_check_mark"],
        }
        return httpx.Response(200, json={"id": "provider-message-1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = NtfyPublisher(build_settings(), client=client)

    result = publisher.publish(
        title="DueSoon is live",
        message="Azure delivery reached ntfy.",
        priority=4,
        tags=["white_check_mark"],
    )

    assert result.provider_message_id == "provider-message-1"


def test_publish_error_does_not_leak_token_topic_or_response_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="ntfy-secret-token private-student-topic private provider details",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = NtfyPublisher(build_settings(), client=client)

    with pytest.raises(NtfyPublishError) as captured:
        publisher.publish(title="Test", message="Test message")

    rendered = str(captured.value)
    assert "ntfy-secret-token" not in rendered
    assert "private-student-topic" not in rendered
    assert "private provider details" not in rendered
    assert "status 500" in rendered
