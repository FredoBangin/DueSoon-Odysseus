"""Browser-session-only dashboard APIs."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.duesoon.api.dependencies import require_browser_session, require_csrf

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_browser_session)])


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.get("/briefing")
def briefing(request: Request):
    return request.app.state.briefing.snapshot()


@router.get("/calendar")
def calendar(request: Request, start: date, end: date):
    try:
        return request.app.state.briefing.calendar(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assistant", dependencies=[Depends(require_csrf)])
def assistant(payload: AssistantRequest, request: Request):
    return request.app.state.assistant.answer(payload.question, request.app.state.briefing.snapshot())


@router.get("/notifications")
def notifications(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    return request.app.state.briefing.notifications(limit)


@router.get("/review")
def review():
    return {"enabled": False, "items": [], "message": "Learning review becomes available after the web MVP is stable."}


@router.get("/settings")
def settings(request: Request):
    value = request.app.state.settings
    return {"canvas": {"configured": value.canvas_enabled, "status": "connected" if value.canvas_enabled else "disabled"},
            "notifications": {"configured": value.ntfy_enabled, "status": "connected" if value.ntfy_enabled else "disabled"},
            "scheduler": {"enabled": value.scheduler_enabled, "interval_seconds": value.scheduler_interval_seconds},
            "dry_run": value.dry_run,
            "features": {name: "deferred" for name in ("model_assistant", "gmail", "google_calendar", "notes", "memory", "documents")}}
