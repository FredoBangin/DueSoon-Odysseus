"""Read-only Canvas REST API client."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from src.duesoon.config.settings import DueSoonSettings


class CanvasAPIError(RuntimeError):
    """Sanitized Canvas request failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CanvasClient:
    """Small read-only client for student Canvas data."""

    _RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        settings: DueSoonSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.canvas_base_url or settings.canvas_access_token is None:
            raise ValueError("Canvas settings are incomplete")
        self.base_url = settings.canvas_base_url
        self._origin = self._url_origin(self.base_url)
        self._max_attempts = settings.canvas_max_attempts
        self._sleep = sleep
        self._client = httpx.Client(
            headers={
                "Authorization": (
                    f"Bearer {settings.canvas_access_token.get_secret_value()}"
                ),
                "Accept": "application/json",
            },
            timeout=settings.canvas_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CanvasClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def list_courses(self) -> list[dict[str, Any]]:
        return self._paginate(
            "/api/v1/courses",
            params={"per_page": 100, "enrollment_type": "student"},
        )

    def list_assignments(self, course_id: str) -> list[dict[str, Any]]:
        return self._paginate(
            f"/api/v1/courses/{course_id}/assignments",
            params={
                "per_page": 100,
                "include[]": ["submission", "all_dates"],
                "order_by": "due_at",
            },
        )

    def _paginate(self, path: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        items: list[dict[str, Any]] = []
        current_params: dict[str, Any] | None = params

        while url:
            self._assert_same_origin(url)
            response = self._request(url, params=current_params)
            payload = response.json()
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise CanvasAPIError("Canvas returned an invalid list response")
            items.extend(payload)
            next_url = response.links.get("next", {}).get("url")
            if next_url:
                self._assert_same_origin(next_url)
            url = next_url
            current_params = None

        return items

    def _request(self, url: str, *, params: dict[str, Any] | None) -> httpx.Response:
        for attempt in range(self._max_attempts):
            try:
                response = self._client.get(url, params=params)
            except httpx.RequestError as exc:
                if attempt + 1 == self._max_attempts:
                    raise CanvasAPIError("Canvas request failed") from exc
                self._sleep(0.5 * (2**attempt))
                continue

            if response.status_code < 400:
                return response
            if response.status_code not in self._RETRYABLE_STATUS or attempt + 1 == self._max_attempts:
                raise CanvasAPIError(
                    f"Canvas request failed with HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            self._sleep(self._retry_delay(response, attempt))

        raise CanvasAPIError("Canvas request failed")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return 0.5 * (2**attempt)

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port

    def _assert_same_origin(self, url: str) -> None:
        if self._url_origin(url) != self._origin:
            raise CanvasAPIError("Canvas returned a cross-origin pagination link")
