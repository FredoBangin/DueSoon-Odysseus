from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src/duesoon/web/static"
AUTH = (Path(__file__).resolve().parents[2] / "src/duesoon/api/routes/auth.py").read_text(encoding="utf-8")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shell_keeps_odysseus_structure_palette_and_all_due_soon_tabs() -> None:
    html = (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")
    css = (ROOT.parents[3] / "static/style.css").read_text(encoding="utf-8")

    assert 'class="sidebar"' in html
    assert 'class="sidebar-header"' in html
    assert 'class="sidebar-inner"' in html
    assert 'class="hamburger-btn"' in html
    for label in ("Calendar", "Email", "Brain", "Notes", "Tasks", "Theme", "Library"):
        assert label in html

    assert "--bg: #282c34" in css
    assert "--fg: #9cdef2" in css
    assert "--panel: #111" in css
    assert "--border: #355a66" in css
    assert "--red: #e06c75" in css
    assert "'Fira Code'" in css


def test_due_soon_uses_inherited_shell_and_has_no_duplicate_css_layer() -> None:
    assert not (ROOT / "css/app.css").exists()
    assert "ODYSSEUS_STATIC" in AUTH
    assert 'read_text(encoding="utf-8")' in AUTH
    assert 'src="/assets/js/odysseus-shell.js"' in AUTH


def test_calendar_retains_odysseus_controls_and_read_only_detail_behavior() -> None:
    source = read("js/views/calendar.js")

    for mode in ('"month"', '"week"', '"agenda"'):
        assert mode in source
    for label in ("Previous", "Today", "Next"):
        assert label in source
    assert "duesoon-calendar-detail" in source
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


def test_shell_does_not_surface_internal_canvas_freshness_badges() -> None:
    html = (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")
    source = read("js/app.js")

    assert "sidebar-freshness" not in html
    assert 'id="freshness"' not in html
    assert "Canvas fresh" not in html
    assert "sidebarFresh" not in source
    assert "fresh.textContent" not in source


def test_shell_runs_inherited_odysseus_background_and_theme_controls() -> None:
    html = (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")
    source = read("js/odysseus-shell.js")

    assert 'bg-pattern-constellations' in html or 'bg-pattern-constellations' in AUTH
    assert 'src="/assets/js/odysseus-shell.js"' in AUTH
    assert 'id="tool-theme-btn"' in html
    assert 'id="theme-modal"' in (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")
    assert 'id="sidebar-toggle-btn"' in html
    assert 'from "/static/js/theme.js"' in source
    assert 'applyBgPattern("constellations")' in source
    assert "applyColors" in source


def test_shell_uses_odysseus_sections_and_account_bar_for_all_due_soon_views() -> None:
    html = (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")

    assert 'id="sessions-section"' in html
    assert 'id="email-section"' in html
    assert 'id="tools-section"' in html
    assert 'id="sidebar-user-bar"' in html
    assert 'id="user-bar-profile"' in html
    assert 'id="user-bar-settings"' in html
    for element in ("rail-calendar", "rail-email", "rail-memory", "rail-notes", "rail-archive", "rail-tasks", "rail-settings"):
        assert f'id="{element}"' in html
    for element in ("sidebar-brand-btn", "user-bar-profile", "user-bar-settings"):
        assert f'id="{element}"' in html


def test_compact_navigation_reuses_odysseus_svg_icons_not_placeholder_glyphs() -> None:
    html = (Path(__file__).resolve().parents[2] / "static/index.html").read_text(encoding="utf-8")
    rail = html.split('<div class="icon-rail"', 1)[1].split("</div>\n\n  <nav", 1)[0]

    assert rail.count("<svg") >= 9
    for placeholder in ("⌂", "◇", "□", "✉", "♢", "▤", "◉", "▧", "⚙"):
        assert placeholder not in rail


def test_inherited_odysseus_assets_are_included_in_production_build_context() -> None:
    dockerignore = (ROOT.parents[3] / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (ROOT.parents[3] / "Dockerfile").read_text(encoding="utf-8")

    assert "\nstatic/\n" not in f"\n{dockerignore}"
    assert "COPY --chown=duesoon:duesoon static ./static" in dockerfile


def test_login_uses_same_odysseus_visual_language() -> None:
    html = read("login.html")

    assert 'href="/static/style.css"' in html
    assert 'class="modal-content"' in html
    assert "DueSoon" in html
    assert "Odysseus" in html
