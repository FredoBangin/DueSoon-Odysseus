"""Deterministic, evidence-backed prose for Discord academic updates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.persistence.models import Assignment


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _text(value: str, limit: int = 100) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _label(assignment: Assignment) -> str:
    course = assignment.course.name.partition("|")[2].strip() or assignment.course.name
    return f"{_text(course, 45)} — {_text(assignment.canonical_title)}"


def _date(value: datetime, local_now: datetime) -> str:
    local = _utc(value).astimezone(local_now.tzinfo)
    date = f"{local.strftime('%A, %B')} {local.day}"
    if local.year != local_now.year:
        date += f", {local.year}"
    return f"{date} at {local.strftime('%I:%M %p %Z').lstrip('0')}"


def school_update(
    assignments: list[Assignment], *, original_message: str,
    completed: list[Assignment], announcements: int,
    window_start: datetime, now: datetime, timezone: str,
) -> tuple[str, str]:
    """Summarize only the listed deadlines and verified, recent source observations."""
    now = _utc(now)
    local_now = now.astimezone(ZoneInfo(timezone))
    effective = [project_canvas_assignment(item) for item in assignments]
    deadlines = [_utc(item.operational_due_at) for item in effective if item.operational_due_at]
    soon = sum(now <= due <= now + timedelta(hours=48) for due in deadlines)
    overdue = sum(due < now for due in deadlines)
    conflicts = sum(item.deadline_status == "conflicted" for item in effective)
    overview = (
        f"Here's your school update. Of the {len(assignments)} unfinished items listed below, "
        f"{soon} are due within 48 hours and {overdue} are overdue."
    )
    if conflicts:
        overview += f" {conflicts} deadlines need review; their earliest credible dates are shown."
    sections = [overview, original_message]

    changes: list[str] = []
    for assignment, item in zip(assignments, effective):
        if item.deadline_status != "resolved" or item.operational_due_at is None:
            continue
        snapshots = sorted(assignment.snapshots, key=lambda value: (_utc(value.observed_at), value.id), reverse=True)
        # Locate the actual date transition, not a later unrelated title/points edit.
        transition = next(((newer, older) for newer, older in zip(snapshots, snapshots[1:])
                           if newer.due_at != older.due_at), None)
        if transition is None:
            continue
        newer, older = transition
        if not (_utc(window_start) < _utc(newer.observed_at) <= now) or newer.due_at is None:
            continue
        if _utc(newer.due_at) != _utc(item.operational_due_at):
            continue
        before = _date(older.due_at, local_now) if older.due_at else "no recorded date"
        changes.append(f"{_label(assignment)}: deadline updated from {before} to {_date(item.operational_due_at, local_now)}.")
    if changes:
        sections.append("Deadline changes\n" + "\n".join(changes[:3]))
    if completed:
        lines = []
        for assignment in completed:
            timestamp = assignment.submission.submitted_at or assignment.submission.graded_at
            lines.append(f"{_label(assignment)} — completed in Canvas; recorded {_date(timestamp, local_now)}.")
        sections.append("Recently completed\n" + "\n".join(lines))
    if announcements:
        noun = "announcement" if announcements == 1 else "announcements"
        sections.append(f"Course updates\n{announcements} new Canvas {noun} recorded. Open DueSoon to review them; their content is not copied here.")
    if changes or completed or announcements:
        sections.append(f"Update window: {_date(window_start, local_now)} through {_date(now, local_now)}.")
    title = f"Your school update · {local_now.strftime('%A, %B')} {local_now.day}, {local_now.year}"
    return title, "\n\n".join(sections)
