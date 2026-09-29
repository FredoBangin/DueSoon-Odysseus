from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.duesoon.notifications.briefing import school_update


NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def assignment(snapshots):
    return SimpleNamespace(
        id=1,
        canvas_assignment_id="1",
        course=SimpleNamespace(canvas_course_id="42", name="ABC | Sample Course"),
        canonical_title="Sample lab",
        submission=None,
        snapshots=snapshots,
        evidence=[],
        canvas_due_at=NOW + timedelta(hours=5),
        canvas_updated_at=NOW,
        updated_at=NOW,
        points_possible=10,
        html_url=None,
    )


def render(item):
    return school_update(
        [item],
        original_message="Due Today\nSample lab — Mon, Sep 28 at 1:00 PM EDT",
        completed=[],
        announcements=0,
        window_start=NOW - timedelta(hours=24),
        now=NOW,
        timezone="America/New_York",
    )


def test_update_reports_actual_transition_with_full_dates():
    old = SimpleNamespace(id=1, due_at=NOW + timedelta(days=3), observed_at=NOW - timedelta(days=2))
    new = SimpleNamespace(id=2, due_at=NOW + timedelta(hours=5), observed_at=NOW - timedelta(hours=1))
    title, body = render(assignment([old, new]))
    assert title == "Your school update · Monday, September 28, 2026"
    assert "Deadline changes" in body
    assert "Thursday, October 1 at 8:00 AM EDT" in body
    assert "Monday, September 28 at 1:00 PM EDT" in body


def test_later_points_edit_does_not_make_an_old_deadline_change_look_new():
    old = SimpleNamespace(id=1, due_at=NOW + timedelta(days=3), observed_at=NOW - timedelta(days=4))
    changed = SimpleNamespace(id=2, due_at=NOW + timedelta(hours=5), observed_at=NOW - timedelta(days=3))
    points_edit = SimpleNamespace(id=3, due_at=changed.due_at, observed_at=NOW - timedelta(hours=1))
    _, body = render(assignment([old, changed, points_edit]))
    assert "Deadline changes" not in body
    assert "Recently completed" not in body
    assert "Course updates" not in body
