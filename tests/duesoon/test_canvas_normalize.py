from __future__ import annotations

import pytest

from src.duesoon.canvas.normalize import (
    normalize_assignment,
    normalize_course,
    normalize_submission,
)


def test_course_normalization_preserves_academic_identity() -> None:
    normalized = normalize_course(
        {
            "id": 42,
            "name": "Network Security",
            "course_code": "CIS-420",
            "time_zone": "America/New_York",
            "workflow_state": "available",
            "term": {"name": "Fall 2026"},
        }
    )

    assert normalized == {
        "canvas_course_id": "42",
        "name": "Network Security",
        "course_code": "CIS-420",
        "timezone": "America/New_York",
        "term": "Fall 2026",
        "active": True,
    }


def test_assignment_normalization_handles_null_dates() -> None:
    normalized = normalize_assignment(
        {
            "id": 99,
            "name": "Lab 1",
            "description": "Do the lab",
            "due_at": None,
            "unlock_at": None,
            "lock_at": None,
            "points_possible": 25,
            "submission_types": ["online_upload"],
            "grading_type": "points",
            "html_url": "https://school.instructure.com/courses/42/assignments/99",
            "workflow_state": "published",
            "published": True,
            "updated_at": "2026-08-26T12:00:00Z",
        }
    )

    assert normalized["canvas_assignment_id"] == "99"
    assert normalized["canonical_title"] == "Lab 1"
    assert normalized["canvas_due_at"] is None
    assert normalized["points_possible"] == 25.0
    assert normalized["assignment_type"] == "online_upload"
    assert len(normalized["description_hash"]) == 64


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"workflow_state": "unsubmitted"}, "not_submitted"),
        ({"workflow_state": "submitted", "submitted_at": "2026-08-26T12:00:00Z"}, "submitted"),
        ({"workflow_state": "graded", "graded_at": "2026-08-26T13:00:00Z"}, "graded"),
        ({"workflow_state": "unsubmitted", "missing": True}, "missing"),
        ({"workflow_state": "unsubmitted", "late": True}, "late"),
        ({"workflow_state": "pending_review"}, "unknown"),
    ],
)
def test_submission_status_normalization(raw: dict, expected: str) -> None:
    assert normalize_submission(raw)["normalized_status"] == expected
