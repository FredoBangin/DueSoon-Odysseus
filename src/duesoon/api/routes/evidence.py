"""Authenticated evidence inspection and owner deadline confirmation routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request

from src.duesoon.api.dependencies import require_api_token
from src.duesoon.api.schemas import (
    ConfirmDeadlineRequest,
    ConfirmDeadlineResponse,
    EvidenceInspectionResponse,
)
from src.duesoon.intelligence.service import ConfirmationResult, EvidenceInspection


router = APIRouter(
    prefix="/api/v1/assignments",
    tags=["academic evidence"],
    dependencies=[Depends(require_api_token)],
)


def inspection_response(value: EvidenceInspection) -> EvidenceInspectionResponse:
    return EvidenceInspectionResponse.model_validate(asdict(value))


def confirmation_response(value: ConfirmationResult) -> ConfirmDeadlineResponse:
    return ConfirmDeadlineResponse(
        created=value.created,
        evidence_id=value.evidence_id,
        inspection=inspection_response(value.inspection),
    )


@router.get("/{assignment_id}/evidence", response_model=EvidenceInspectionResponse)
def assignment_evidence(assignment_id: int, request: Request) -> EvidenceInspectionResponse:
    try:
        return inspection_response(request.app.state.evidence.inspect(assignment_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{assignment_id}/confirm-deadline", response_model=ConfirmDeadlineResponse)
def confirm_assignment_deadline(
    assignment_id: int,
    payload: ConfirmDeadlineRequest,
    request: Request,
) -> ConfirmDeadlineResponse:
    try:
        result = request.app.state.evidence.confirm_deadline(assignment_id, payload.due_at)
        return confirmation_response(result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
