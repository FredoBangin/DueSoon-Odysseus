"""Owner login and protected application documents."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from src.duesoon.api.dependencies import require_browser_session, require_csrf
from src.duesoon.auth.service import InvalidCredentials, LoginRateLimited, SessionPrincipal

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
ODYSSEUS_STATIC = Path(__file__).resolve().parents[4] / "static"
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
    return FileResponse(
        STATIC / "login.html",
        headers={
            "Cache-Control": "no-store",
            "Clear-Site-Data": '"cache", "storage"',
        },
    )


@router.get("/app")
@router.get("/app/{path:path}")
def app_page(request: Request, path: str = ""):
    try:
        require_browser_session(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    # Keep the complete Odysseus DOM as the product shell.  DueSoon owns the
    # protected data/views, so the legacy Odysseus runtime is intentionally not
    # loaded here (its old API endpoints would be unsafe to call).  This small
    # adapter replaces only the chat-history mount point and wires our bounded
    # DueSoon modules into the inherited markup/CSS.
    html = (ODYSSEUS_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("<title>Odysseus Chat</title>", "<title>DueSoon</title>")
    html = html.replace("<body>", '<body class="bg-pattern-constellations">', 1)
    html = re.sub(r'href="/static/style\.css[^"]*"', 'href="/static/style.css"', html, count=1)
    html = html.replace('class="sidebar-brand-title">Odysseus</', 'class="sidebar-brand-title">DueSoon</')
    html = html.replace('title="New chat"', 'title="DueSoon home"')
    html = re.sub(
        r'\s*<div class="list-item" id="sidebar-new-chat-btn".*?</div>\s*',
        "\n",
        html,
        count=1,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'\s*<button class="icon-rail-btn rail-new-chat" id="rail-new-session".*?</button>\s*',
        "\n",
        html,
        count=1,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'<div id="chat-history" class="chat-history"[^>]*></div>',
        '<section id="content" class="chat-history" role="log" aria-live="polite"></section>',
        html,
        count=1,
    )
    duesoon_navigation = '''
      <div class="section" id="duesoon-section">
        <div class="section-header-flex">
          <span class="section-title"><span class="section-title-label">Academic</span></span>
          <button type="button" class="section-collapse-btn" aria-label="Collapse Academic" aria-expanded="true">
            <svg class="section-collapse-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div id="duesoon-items">
          <div class="list-item" data-view="home" role="button" tabindex="0"><span class="grow">Home</span></div>
          <div class="list-item" data-view="assistant" role="button" tabindex="0"><span class="grow">Assistant</span></div>
          <div class="list-item" data-view="calendar" role="button" tabindex="0"><span class="grow">Calendar</span></div>
          <div class="list-item" data-view="email" role="button" tabindex="0"><span class="grow">Email</span></div>
          <div class="list-item" data-view="notifications" role="button" tabindex="0"><span class="grow">Notifications</span></div>
          <div class="list-item" data-view="review" role="button" tabindex="0"><span class="grow">Review</span></div>
        </div>
      </div>
'''
    html = html.replace('<div class="section" id="sessions-section">', duesoon_navigation + '<div class="section" id="sessions-section">', 1)
    html = html.replace('<div id="welcome-screen">', '<div id="welcome-screen" class="hidden">', 1)
    html = html.replace('class="chat-container welcome-active"', 'class="chat-container"', 1)
    # The original page has many independently loaded feature runtimes.  They
    # are UI-only dependencies of Odysseus and would call APIs absent from the
    # DueSoon service; retain their markup/assets but let DueSoon JS own events.
    html = re.sub(r'\s*<script[^>]+src="/static/[^>]+></script>', "", html)
    html = re.sub(r'\s*<link[^>]+rel="modulepreload"[^>]+>', "", html)
    html = re.sub(r'\s*<script[^>]*>[^<]*serviceWorker[^<]*</script>', "", html)
    html = html.replace(
        "</body>",
        '  <script type="module" src="/assets/js/odysseus-shell.js"></script>\n'
        '  <script type="module" src="/assets/js/app.js"></script>\n</body>',
        1,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
