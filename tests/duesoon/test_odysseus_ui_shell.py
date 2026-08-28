from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src/duesoon/web/static"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shell_keeps_odysseus_structure_palette_and_all_due_soon_tabs() -> None:
    html = read("index.html")
    css = read("css/app.css")

    assert 'class="sidebar"' in html
    assert 'class="sidebar-header"' in html
    assert 'class="sidebar-inner"' in html
    assert 'class="hamburger-btn"' in html
    for label in (
        "Home",
        "Assistant",
        "Calendar",
        "Email",
        "Notifications",
        "Review",
        "Settings",
        "Notes",
        "Memory",
        "Documents",
    ):
        assert f">{label}<" in html

    assert "--bg: #282c34" in css
    assert "--fg: #9cdef2" in css
    assert "--panel: #111" in css
    assert "--border: #355a66" in css
    assert "--red: #e06c75" in css
    assert "'Fira Code'" in css


def test_calendar_retains_odysseus_controls_and_read_only_detail_behavior() -> None:
    source = read("js/views/calendar.js")

    for mode in ('"month"', '"week"', '"agenda"'):
        assert mode in source
    for label in ("Previous", "Today", "Next"):
        assert label in source
    assert "detail-drawer" in source
    assert "Open in Canvas" in source
    assert all(word not in source for word in ("createEvent", "updateEvent", "deleteEvent"))


def test_frontend_runtime_remains_bounded_and_browser_secret_free() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.glob("js/**/*.js"))

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "serviceWorker",
        "X-API-Token",
        "/api/tools",
        "/api/execute",
    ):
        assert forbidden not in source
    assert "/api/v1/dashboard/briefing" in source
    assert "/api/v1/dashboard/assistant" in source
    assert "/api/v1/dashboard/calendar" in source


def test_login_uses_same_odysseus_visual_language() -> None:
    html = read("login.html")

    assert 'class="login-shell"' in html
    assert "DueSoon" in html
    assert "Odysseus" in html
