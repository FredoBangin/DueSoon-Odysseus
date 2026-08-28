"""Authentication dependencies with separate API and browser boundaries."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request

from src.duesoon.auth.service import SessionPrincipal


def require_api_token(request: Request, x_api_token: str | None = Header(default=None)) -> None:
    configured = request.app.state.settings.api_token
    if configured is None:
        return
    if x_api_token is None or not secrets.compare_digest(x_api_token, configured.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid API token")


def require_browser_session(request: Request) -> SessionPrincipal:
    name = request.app.state.settings.session_cookie_name
    principal = request.app.state.auth.authenticate(request.cookies.get(name, ""))
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def require_csrf(request: Request) -> SessionPrincipal:
    principal = require_browser_session(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(supplied, principal.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return principal
