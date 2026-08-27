from __future__ import annotations

import httpx
import pytest

from src.duesoon.canvas.client import CanvasAPIError, CanvasClient
from src.duesoon.config.settings import DueSoonSettings


def settings() -> DueSoonSettings:
    return DueSoonSettings(
        _env_file=None,
        canvas_enabled=True,
        canvas_base_url="https://school.instructure.com",
        canvas_access_token="canvas-secret",
    )


def test_list_courses_uses_bearer_auth_and_follows_opaque_next_link() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer canvas-secret"
        if len(requests) == 1:
            assert request.url.params["per_page"] == "100"
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={
                    "Link": '<https://school.instructure.com/api/v1/courses?page=opaque-token>; rel="next"'
                },
            )
        return httpx.Response(200, json=[{"id": 2}])

    client = CanvasClient(settings(), transport=httpx.MockTransport(handler))
    try:
        courses = client.list_courses()
    finally:
        client.close()

    assert courses == [{"id": 1}, {"id": 2}]
    assert str(requests[1].url) == (
        "https://school.instructure.com/api/v1/courses?page=opaque-token"
    )


def test_assignment_request_includes_current_user_submission() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/courses/42/assignments"
        assert request.url.params.get_list("include[]") == ["submission", "all_dates"]
        return httpx.Response(200, json=[])

    client = CanvasClient(settings(), transport=httpx.MockTransport(handler))
    try:
        assert client.list_assignments("42") == []
    finally:
        client.close()


def test_cross_origin_pagination_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://evil.example/api/v1/courses?page=2>; rel="next"'},
        )

    client = CanvasClient(settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CanvasAPIError, match="cross-origin"):
            client.list_courses()
    finally:
        client.close()


def test_rate_limit_is_retried() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[])

    client = CanvasClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )
    try:
        assert client.list_courses() == []
    finally:
        client.close()

    assert attempts == 2
    assert sleeps == [0.0]


def test_error_never_contains_access_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "canvas-secret"})

    client = CanvasClient(settings(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CanvasAPIError) as caught:
            client.list_courses()
    finally:
        client.close()

    assert "canvas-secret" not in str(caught.value)
    assert caught.value.status_code == 401
