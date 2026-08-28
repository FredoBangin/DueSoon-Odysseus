"""Owner login and protected application documents."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.duesoon.api.dependencies import require_browser_session, require_csrf
from src.duesoon.auth.service import InvalidCredentials, LoginRateLimited, SessionPrincipal

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    settings = request.app.state.settings
    if not settings.web_enabled:
        raise HTTPException(status_code=404, detail="not found")
    origin = request.headers.get("Origin")
    if settings.public_origin and origin != settings.public_origin:
        raise HTTPException(status_code=403, detail="origin validation failed")
    try:
        created = request.app.state.auth.login(payload.username, payload.password,
                                               request.client.host if request.client else "unknown")
    except LoginRateLimited as exc:
        raise HTTPException(status_code=429, detail="login temporarily unavailable") from exc
    except InvalidCredentials as exc:
        raise HTTPException(status_code=401, detail="invalid credentials") from exc
    response.set_cookie(settings.session_cookie_name, created.raw_token, httponly=True,
                        secure=settings.environment == "production", samesite="strict",
                        path="/", max_age=settings.session_ttl_minutes * 60)
    response.headers["Cache-Control"] = "no-store"
    return {"username": settings.owner_username, "csrf_token": created.csrf_token,
            "expires_at": created.expires_at}


@router.get("/api/v1/auth/session")
def session(principal: SessionPrincipal = Depends(require_browser_session)) -> dict[str, object]:
    return {"username": principal.username, "csrf_token": principal.csrf_token,
            "expires_at": principal.expires_at}


@router.post("/api/v1/auth/logout")
def logout(request: Request, response: Response,
           _principal: SessionPrincipal = Depends(require_csrf)) -> dict[str, bool]:
    name = request.app.state.settings.session_cookie_name
    request.app.state.auth.revoke(request.cookies.get(name, ""))
    response.delete_cookie(name, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"logged_out": True}


@router.get("/")
def root(request: Request):
    return RedirectResponse("/app" if request.cookies.get(request.app.state.settings.session_cookie_name) else "/login")


@router.get("/login")
def login_page() -> FileResponse:
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})


@router.get("/app")
@router.get("/app/{path:path}")
def app_page(request: Request, path: str = ""):
    try:
        require_browser_session(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
