"""Pure Canvas payload normalization."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


def _iso_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def normalize_course(raw: dict[str, Any]) -> dict[str, Any]:
    term = raw.get("term")
    return {
        "canvas_course_id": str(raw["id"]),
        "name": str(raw.get("name") or raw.get("course_code") or raw["id"]),
        "course_code": raw.get("course_code"),
        "timezone": raw.get("time_zone"),
        "term": term.get("name") if isinstance(term, dict) else None,
        "active": raw.get("workflow_state") not in {"completed", "deleted"},
    }


def normalize_assignment(raw: dict[str, Any]) -> dict[str, Any]:
    description = str(raw.get("description") or "")
    submission_types = [str(item) for item in (raw.get("submission_types") or [])]
    assignment_type = "quiz" if raw.get("quiz_id") else (
        submission_types[0] if submission_types else "none"
    )
    points = raw.get("points_possible")
    return {
        "canvas_assignment_id": str(raw["id"]),
        "canonical_title": str(raw.get("name") or raw["id"]),
        "description_hash": hashlib.sha256(description.encode("utf-8")).hexdigest(),
        "canvas_due_at": _iso_datetime(raw.get("due_at")),
        "unlock_at": _iso_datetime(raw.get("unlock_at")),
        "lock_at": _iso_datetime(raw.get("lock_at")),
        "points_possible": float(points) if points is not None else None,
        "assignment_type": assignment_type,
        "submission_types": submission_types,
        "grading_type": raw.get("grading_type"),
        "html_url": raw.get("html_url"),
        "workflow_state": raw.get("workflow_state"),
        "published": bool(raw.get("published", False)),
        "canvas_updated_at": _iso_datetime(raw.get("updated_at")),
    }


def normalize_submission(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = raw or {}
    workflow_state = payload.get("workflow_state")
    if payload.get("graded_at") or workflow_state == "graded":
        status = "graded"
    elif payload.get("missing"):
        status = "missing"
    elif payload.get("late"):
        status = "late"
    elif payload.get("submitted_at") or workflow_state == "submitted":
        status = "submitted"
    elif workflow_state in {"unsubmitted", "new", None}:
        status = "not_submitted"
    else:
        status = "unknown"

    return {
        "external_submission_id": (
            str(payload["id"]) if payload.get("id") is not None else None
        ),
        "normalized_status": status,
        "raw_status": str(workflow_state) if workflow_state is not None else None,
        "submitted_at": _iso_datetime(payload.get("submitted_at")),
        "graded_at": _iso_datetime(payload.get("graded_at")),
        "missing": bool(payload.get("missing", False)),
        "late": bool(payload.get("late", False)),
    }
