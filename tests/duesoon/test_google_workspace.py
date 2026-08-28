from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from src.duesoon.google import GoogleWorkspaceClient, GoogleWorkspaceConfig


def test_google_workspace_is_read_only_and_reuses_access_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST"
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer access"
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if request.url.path.endswith("/messages/m1"):
            return httpx.Response(200, json={
                "id": "m1", "threadId": "t1", "snippet": "Deadline update",
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "Subject", "value": "Lab moved"},
                        {"name": "From", "value": "Professor <p@example.edu>"},
                    ],
                    "parts": [{"mimeType": "text/plain", "body": {"data": "RHVlIEZyaWRheQ"}}],
                },
            })
        return httpx.Response(200, json={"items": [{
            "id": "e1", "summary": "Office hours",
            "start": {"dateTime": "2026-08-29T14:00:00-04:00"},
            "end": {"dateTime": "2026-08-29T15:00:00-04:00"},
            "htmlLink": "https://calendar.google.com/event/e1",
        }]})

    config = GoogleWorkspaceConfig(
        _env_file=None,
        enabled=True,
        gmail_enabled=True,
        calendar_enabled=True,
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )
    client = GoogleWorkspaceClient(config, transport=httpx.MockTransport(handler), clock=lambda: 1000)
    try:
        messages = client.list_gmail_messages(limit=1)
        events = client.list_calendar_events(
            start=datetime(2026, 8, 28, tzinfo=UTC),
            end=datetime(2026, 8, 28, tzinfo=UTC) + timedelta(days=7),
        )
    finally:
        client.close()

    assert messages[0]["subject"] == "Lab moved"
    assert messages[0]["body"] == "Due Friday"
    assert events[0]["read_only"] is True
    assert sum(request.url.host == "oauth2.googleapis.com" for request in requests) == 1
    assert all(request.method in {"GET", "POST"} for request in requests)
