from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src/duesoon/web/static"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shell_keeps_odysseus_structure_palette_and_all_due_soon_tabs() -> None:
    html = read("index.html")
    css = (ROOT.parents[3] / "static/style.css").read_text(encoding="utf-8")

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


def test_due_soon_bridge_css_does_not_replace_the_odysseus_shell() -> None:
    css = read("css/app.css")

    for forbidden in (
        "\nbody {",
        "\n.sidebar {",
        "\n.sidebar-header {",
        "\n.sidebar-inner {",
        "\n.hamburger-btn {",
        "\n.icon-rail {",
    ):
        assert forbidden not in f"\n{css}"
    assert ".duesoon-workspace" in css


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


def test_shell_does_not_surface_internal_canvas_freshness_badges() -> None:
    html = read("index.html")
    source = read("js/app.js")

    assert "sidebar-freshness" not in html
    assert 'id="freshness"' not in html
    assert "Canvas fresh" not in html
    assert "sidebarFresh" not in source
    assert "fresh.textContent" not in source


def test_shell_runs_inherited_odysseus_background_and_theme_controls() -> None:
    html = read("index.html")
    source = read("js/odysseus-shell.js")

    assert 'class="bg-pattern-constellations"' in html
    assert 'src="/assets/js/odysseus-shell.js"' in html
    assert 'id="tool-theme-btn"' in html
    assert 'id="theme-submenu"' in html
    assert 'id="sidebar-toggle-btn"' in html
    assert 'from "/static/js/theme.js"' in source
    assert 'applyBgPattern("constellations")' in source
    assert "applyColors" in source


def test_shell_uses_odysseus_sections_and_account_bar_for_all_due_soon_views() -> None:
    html = read("index.html")

    assert 'id="sidebar-new-chat-btn"' not in html
    assert html.count('class="section-collapse-btn"') == 2
    assert 'aria-label="Collapse Academic"' in html
    assert 'aria-label="Collapse Tools"' in html
    assert 'class="section" id="academic-section"' in html
    assert 'class="section" id="retained-tools-section"' in html
    assert 'id="sidebar-user-bar"' in html
    assert 'id="user-bar-profile"' in html
    assert 'id="user-bar-settings"' in html
    for view in (
        "home",
        "assistant",
        "calendar",
        "email",
        "notifications",
        "review",
        "settings",
        "notes",
        "memory",
        "documents",
    ):
        assert f'data-view="{view}"' in html


def test_compact_navigation_reuses_odysseus_svg_icons_not_placeholder_glyphs() -> None:
    html = read("index.html")
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

    assert 'class="login-shell"' in html
    assert "DueSoon" in html
    assert "Odysseus" in html
