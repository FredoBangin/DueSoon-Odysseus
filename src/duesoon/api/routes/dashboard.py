"""Browser-session-only dashboard APIs."""

from datetime import UTC, date, datetime, time
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.duesoon.api.dependencies import require_browser_session, require_csrf
from src.duesoon.api.routes.evidence import confirmation_response, inspection_response
from src.duesoon.api.schemas import (
    ConfirmDeadlineRequest,
    ConfirmDeadlineResponse,
    EvidenceInspectionResponse,
)
from src.duesoon.google import GoogleAPIError

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_browser_session)])
logger = logging.getLogger(__name__)


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


class NoteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10000)
    assignment_id: int | None = Field(default=None, ge=1)
    course_id: int | None = Field(default=None, ge=1)


class NoteUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    archived: bool | None = None


class MemoryCreateRequest(BaseModel):
    memory_type: str = Field(min_length=1, max_length=50)
    scope_type: str = Field(min_length=1, max_length=30)
    scope_ref: str | None = Field(default=None, max_length=255)
    label: str = Field(min_length=1, max_length=500)
    value: str = Field(min_length=1, max_length=5000)


class MemoryUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=500)
    value: str | None = Field(default=None, min_length=1, max_length=5000)
    active: bool | None = None


class PlanningUpdateRequest(BaseModel):
    estimated_minutes: int | None = Field(default=None, ge=5, le=10_080)
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=2000)


@router.get("/briefing")
def briefing(request: Request):
    return request.app.state.briefing.snapshot()


@router.get("/diagnostics")
def diagnostics(request: Request):
    return request.app.state.diagnostics.snapshot()


@router.get("/calendar")
def calendar(request: Request, start: date, end: date):
    try:
        value = request.app.state.briefing.calendar(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    google = request.app.state.google
    if google is not None and google.config.calendar_enabled:
        try:
            external = google.list_calendar_events(
                start=datetime.combine(start, time.min, tzinfo=UTC),
                end=datetime.combine(end, time.max, tzinfo=UTC),
            )
            for item in external:
                starts_at = str(item.get("starts_at") or "")
                local_date = starts_at[:10]
                local_time = "All day" if item.get("all_day") else _event_time(starts_at)
                value["events"].append({
                    "id": f"google-{item['id']}",
                    "assignment_id": None,
                    "title": item["title"],
                    "course_name": "Google Calendar",
                    "starts_at": starts_at,
                    "local_date": local_date,
                    "local_time": local_time,
                    "color": "#4285f4",
                    "status": item["status"],
                    "urgency_level": "LOW",
                    "source": "google_calendar",
                    "read_only": True,
                    "external_url": item.get("html_url"),
                })
            value["events"].sort(key=lambda item: str(item["starts_at"]))
        except GoogleAPIError:
            value["google_calendar_status"] = "unavailable"
    return value


@router.get("/gmail")
def gmail(
    request: Request,
    query: Annotated[str, Query(max_length=500)] = "label:inbox newer_than:90d",
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
):
    google = request.app.state.google
    if google is None or not google.config.gmail_enabled:
        return {"enabled": False, "items": [], "access": "read_only"}
    try:
        return {
            "enabled": True,
            "items": google.list_gmail_messages(query=query, limit=limit),
            "access": "read_only",
        }
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail="Gmail is temporarily unavailable") from exc


@router.post("/gmail/sync", dependencies=[Depends(require_csrf)])
def sync_gmail(
    request: Request,
    query: Annotated[str, Query(max_length=500)] = "label:inbox newer_than:90d",
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
):
    """Capture read-only Gmail messages as versioned evidence; never alter Gmail."""
    google = request.app.state.google
    if google is None or not google.config.gmail_enabled:
        raise HTTPException(status_code=409, detail="Gmail is not configured")
    try:
        messages = google.list_gmail_messages(query=query, limit=limit)
    except GoogleAPIError as exc:
        raise HTTPException(status_code=502, detail="Gmail is temporarily unavailable") from exc
    result = request.app.state.google_evidence.store_messages(messages)
    model = request.app.state.model_settings.effective()
    if result["stored"] and model.enabled and model.configured:
        try:
            request.app.state.evidence_pipeline.process_pending(
                limit=min(result["stored"], 5)
            )
        except Exception:
            # Capturing read-only Gmail evidence must not fail if optional extraction does.
            logger.exception("Gmail evidence extraction failed")
    return result


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


@router.get(
    "/assignments/{assignment_id}/evidence",
    response_model=EvidenceInspectionResponse,
)
def assignment_evidence(assignment_id: int, request: Request) -> EvidenceInspectionResponse:
    try:
        return inspection_response(request.app.state.evidence.inspect(assignment_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/assignments/{assignment_id}/planning")
def assignment_planning(assignment_id: int, request: Request):
    try:
        return request.app.state.planning.inspect(assignment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/assignments/{assignment_id}/planning",
    dependencies=[Depends(require_csrf)],
)
def update_assignment_planning(
    assignment_id: int,
    payload: PlanningUpdateRequest,
    request: Request,
):
    try:
        return request.app.state.planning.record_owner_update(
            assignment_id,
            **payload.model_dump(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/assignments/{assignment_id}/confirm-deadline",
    response_model=ConfirmDeadlineResponse,
    dependencies=[Depends(require_csrf)],
)
def confirm_assignment_deadline(
    assignment_id: int,
    payload: ConfirmDeadlineRequest,
    request: Request,
) -> ConfirmDeadlineResponse:
    try:
        return confirmation_response(
            request.app.state.evidence.confirm_deadline(assignment_id, payload.due_at)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/notes")
def notes(request: Request, include_archived: bool = False):
    return {"items": request.app.state.retained.notes(include_archived=include_archived)}


@router.post("/notes", dependencies=[Depends(require_csrf)])
def create_note(payload: NoteCreateRequest, request: Request):
    try:
        return request.app.state.retained.create_note(**payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/notes/{note_id}", dependencies=[Depends(require_csrf)])
def update_note(note_id: str, payload: NoteUpdateRequest, request: Request):
    try:
        return request.app.state.retained.update_note(
            note_id, **payload.model_dump(exclude_none=True)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/memories")
def memories(request: Request, include_inactive: bool = False):
    return {"items": request.app.state.retained.memories(include_inactive=include_inactive)}


@router.post("/memories", dependencies=[Depends(require_csrf)])
def create_memory(payload: MemoryCreateRequest, request: Request):
    try:
        return request.app.state.retained.create_memory(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/memories/{memory_id}", dependencies=[Depends(require_csrf)])
def update_memory(memory_id: str, payload: MemoryUpdateRequest, request: Request):
    try:
        return request.app.state.retained.update_memory(
            memory_id, **payload.model_dump(exclude_none=True)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/documents")
def documents(request: Request, limit: Annotated[int, Query(ge=1, le=250)] = 100):
    return {"items": request.app.state.retained.documents(limit=limit), "access": "read_only"}


@router.get("/review")
def review(request: Request):
    return {
        "enabled": True,
        "items": request.app.state.learning.list_proposals(),
        "evidence_items": request.app.state.evidence_review.list_pending(),
        "message": (
            "Review unresolved evidence and learning proposals. Protected academic state "
            "changes still require validated evidence or owner confirmation."
        ),
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
    google = request.app.state.google
    return {"canvas": {"configured": value.canvas_enabled, "status": "connected" if value.canvas_enabled else "disabled"},
            "notifications": {"configured": value.ntfy_enabled, "status": "connected" if value.ntfy_enabled else "disabled"},
            "scheduler": {
                "enabled": value.scheduler_enabled,
                "interval_seconds": value.scheduler_interval_seconds,
                "daily_digest_enabled": value.daily_digest_enabled,
                "daily_digest_hour": value.daily_digest_hour,
                "daily_digest_max_items": value.daily_digest_max_items,
            },
            "dry_run": value.dry_run,
            "features": {
                "model_assistant": "enabled" if model["enabled"] else (
                    "configured" if model["configured"] else "disabled"
                ),
                "gmail": "connected" if google is not None and google.config.gmail_enabled else "disabled",
                "google_calendar": "connected" if google is not None and google.config.calendar_enabled else "disabled",
                "notes": "enabled",
                "memory": "owner-controlled",
                "documents": "read-only",
            }}


def _event_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return ""
