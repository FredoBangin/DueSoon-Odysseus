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


class AssistantFeedbackRequest(BaseModel):
    verdict: str
    what_was_wrong: str | None = Field(default=None, max_length=2000)
    scope_type: str = "global"
    scope_ref: str | None = Field(default=None, max_length=255)


class ReviewActionRequest(BaseModel):
    action: str
    edited_text: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=1000)


class ModelSettingsRequest(BaseModel):
    enabled: bool | None = None
    primary_model: str | None = Field(default=None, max_length=255)
    fallback_models: list[str] | None = Field(default=None, max_length=5)
    timeout_seconds: float | None = Field(default=None, ge=1, le=60)
    max_input_tokens: int | None = Field(default=None, ge=256, le=32000)
    max_output_tokens: int | None = Field(default=None, ge=64, le=4000)
    call_budget: int | None = Field(default=None, ge=1, le=5)


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


@router.post("/assistant/{answer_id}/feedback", dependencies=[Depends(require_csrf)])
def assistant_feedback(
    answer_id: str, payload: AssistantFeedbackRequest, request: Request
):
    try:
        return request.app.state.learning.submit_feedback(
            answer_id,
            verdict=payload.verdict,
            what_was_wrong=payload.what_was_wrong,
            scope_type=payload.scope_type,
            scope_ref=payload.scope_ref,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/notifications")
def notifications(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    return request.app.state.briefing.notifications(limit)


@router.get("/review")
def review(request: Request):
    return {
        "enabled": True,
        "items": request.app.state.learning.list_proposals(),
        "message": "Owner approval is required before any learning guidance becomes active.",
    }


@router.post("/review/{proposal_id}", dependencies=[Depends(require_csrf)])
def review_action(proposal_id: str, payload: ReviewActionRequest, request: Request):
    try:
        return request.app.state.learning.act(
            proposal_id,
            action=payload.action,
            edited_text=payload.edited_text,
            reason=payload.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/model-settings")
def model_settings(request: Request):
    return request.app.state.model_settings.status()


@router.patch("/model-settings", dependencies=[Depends(require_csrf)])
def update_model_settings(payload: ModelSettingsRequest, request: Request):
    values = payload.model_dump(exclude_none=True)
    try:
        return request.app.state.model_settings.update(values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings")
def settings(request: Request):
    value = request.app.state.settings
    model = request.app.state.model_settings.status()
    return {"canvas": {"configured": value.canvas_enabled, "status": "connected" if value.canvas_enabled else "disabled"},
            "notifications": {"configured": value.ntfy_enabled, "status": "connected" if value.ntfy_enabled else "disabled"},
            "scheduler": {"enabled": value.scheduler_enabled, "interval_seconds": value.scheduler_interval_seconds},
            "dry_run": value.dry_run,
            "features": {
                "model_assistant": "enabled" if model["enabled"] else (
                    "configured" if model["configured"] else "disabled"
                ),
                **{name: "deferred" for name in ("gmail", "google_calendar", "notes", "memory", "documents")},
            }}
