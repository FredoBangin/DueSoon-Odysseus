"""Narrow, read-only Gmail and Google Calendar REST client."""

from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .config import GoogleWorkspaceConfig


class GoogleAPIError(RuntimeError):
    """Sanitized Google API failure."""


class GoogleWorkspaceClient:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
    CALENDAR_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(
        self,
        config: GoogleWorkspaceConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not config.enabled or not config.configured:
            raise ValueError("Google Workspace is disabled or incomplete")
        self.config = config
        self._clock = clock
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._client = httpx.Client(
            timeout=config.timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def list_gmail_messages(self, *, query: str = "label:inbox newer_than:90d", limit: int = 25) -> list[dict[str, Any]]:
        if not self.config.gmail_enabled:
            raise GoogleAPIError("Gmail reader is disabled")
        payload = self._get(
            f"{self.GMAIL_URL}/messages",
            params={"q": query, "maxResults": min(max(limit, 1), 50)},
        )
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise GoogleAPIError("Gmail returned an invalid message list")
        values = []
        for item in messages[:limit]:
            message_id = item.get("id") if isinstance(item, dict) else None
            if message_id:
                values.append(self._normalize_message(self._get(
                    f"{self.GMAIL_URL}/messages/{quote(str(message_id), safe='')}",
                    params={"format": "full"},
                )))
        return values

    def list_calendar_events(
        self, *, start: datetime, end: datetime, limit: int = 250
    ) -> list[dict[str, Any]]:
        if not self.config.calendar_enabled:
            raise GoogleAPIError("Google Calendar reader is disabled")
        payload = self._get(
            f"{self.CALENDAR_URL}/calendars/primary/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "showDeleted": "false",
                "maxResults": min(max(limit, 1), 2500),
            },
        )
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise GoogleAPIError("Google Calendar returned an invalid event list")
        return [self._normalize_event(item) for item in items if isinstance(item, dict)]

    def status(self) -> dict[str, bool | str]:
        return {
            "configured": self.config.configured,
            "gmail": self.config.gmail_enabled,
            "calendar": self.config.calendar_enabled,
            "access": "read_only",
        }

    def _get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            try:
                response = self._client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token()}"},
                )
            except httpx.RequestError as exc:
                raise GoogleAPIError("Google API request failed") from exc
            if response.status_code == 401 and attempt == 0:
                self._access_token = None
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise GoogleAPIError(f"Google API request failed ({response.status_code})")
            try:
                payload = response.json()
            except ValueError as exc:
                raise GoogleAPIError("Google API returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise GoogleAPIError("Google API returned an invalid response")
            return payload
        raise GoogleAPIError("Google authorization expired")

    def _token(self) -> str:
        now = self._clock()
        if self._access_token and now < self._expires_at - 60:
            return self._access_token
        try:
            response = self._client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.config.client_id.get_secret_value(),
                    "client_secret": self.config.client_secret.get_secret_value(),
                    "refresh_token": self.config.refresh_token.get_secret_value(),
                    "grant_type": "refresh_token",
                },
            )
        except httpx.RequestError as exc:
            raise GoogleAPIError("Google token refresh failed") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise GoogleAPIError(f"Google token refresh failed ({response.status_code})")
        try:
            payload = response.json()
            token = payload["access_token"]
            expires_in = int(payload.get("expires_in", 3600))
            if not isinstance(token, str) or not token:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleAPIError("Google token refresh returned an invalid response") from exc
        self._access_token = token
        self._expires_at = now + max(expires_in, 60)
        return token

    @staticmethod
    def _normalize_message(value: dict[str, Any]) -> dict[str, Any]:
        payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in payload.get("headers", []) if isinstance(item, dict)
        }
        return {
            "id": str(value.get("id", "")),
            "thread_id": str(value.get("threadId", "")),
            "subject": headers.get("subject", "(no subject)")[:500],
            "from": headers.get("from", "")[:500],
            "date": headers.get("date", "")[:200],
            "snippet": str(value.get("snippet", ""))[:1000],
            "body": _plain_text(payload)[:20000],
            "attachments": _attachments(payload)[:25],
        }

    @staticmethod
    def _normalize_event(value: dict[str, Any]) -> dict[str, Any]:
        start = value.get("start") if isinstance(value.get("start"), dict) else {}
        end = value.get("end") if isinstance(value.get("end"), dict) else {}
        return {
            "id": str(value.get("id", "")),
            "title": str(value.get("summary", "(untitled event)"))[:500],
            "starts_at": start.get("dateTime") or start.get("date"),
            "ends_at": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start,
            "status": str(value.get("status", "confirmed")),
            "html_url": value.get("htmlLink"),
            "source": "google_calendar",
            "read_only": True,
        }


def _plain_text(part: dict[str, Any]) -> str:
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    if part.get("mimeType") == "text/plain" and isinstance(body.get("data"), str):
        try:
            return base64.urlsafe_b64decode(body["data"] + "===").decode("utf-8", "replace")
        except (ValueError, TypeError):
            return ""
    for child in part.get("parts", []):
        if isinstance(child, dict):
            value = _plain_text(child)
            if value:
                return value
    return ""


def _attachments(part: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    filename = part.get("filename")
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    if filename and body.get("attachmentId"):
        values.append({
            "filename": str(filename)[:500],
            "mime_type": str(part.get("mimeType", "application/octet-stream"))[:200],
            "attachment_id": str(body["attachmentId"]),
        })
    for child in part.get("parts", []):
        if isinstance(child, dict):
            values.extend(_attachments(child))
    return values
