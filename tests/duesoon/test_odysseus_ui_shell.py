from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "src/duesoon/web/static"
AUTH = (REPO / "src/duesoon/api/routes/auth.py").read_text(encoding="utf-8")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_curated_shell_reuses_odysseus_assets_and_surfaces_due_soon_views() -> None:
    html = read("index.html")
    inherited_css = (REPO / "static/style.css").read_text(encoding="utf-8")

    for marker in ('class="sidebar"', 'class="icon-rail"', 'class="hamburger-btn"'):
        assert marker in html
    for view in ("home", "assistant", "calendar", "email", "notifications", "review", "memory", "documents", "notes", "settings"):
        assert f'data-view="{view}"' in html
    assert 'href="/static/style.css"' in html
    assert 'href="/assets/css/app.css"' in html
    assert 'id="content" class="workspace-content"' in html
    assert 'id="sidebar-user-bar"' in html
    assert 'id="tool-theme-btn"' in html
    assert 'bg-pattern-constellations' in html
    assert "--bg: #282c34" in inherited_css
    assert "--fg: #9cdef2" in inherited_css
    assert "'Fira Code'" in inherited_css


def test_root_serves_curated_shell_without_runtime_regex_transplant() -> None:
    assert 'FileResponse(STATIC / "index.html"' in AUTH
    assert "ODYSSEUS_STATIC" not in AUTH
    assert "re.sub" not in AUTH
    assert 'src="/assets/js/odysseus-shell.js"' in read("index.html")


def test_scoped_due_soon_css_does_not_replace_inherited_shell() -> None:
    css = read("css/app.css")

    assert ".workspace-content" in css
    assert ".grid" in css
    assert ".panel" in css
    assert ".login-shell" in css
    for broad_selector in ("\nbody {", "\n.sidebar {", "\n.icon-rail {", "\n.chat-container {"):
        assert broad_selector not in css


def test_home_keeps_approved_two_column_briefing_and_embedded_assistant() -> None:
    source = read("js/views/home.js")

    assert 'node("div","","grid")' in source
    assert 'node("article","","panel wide")' in source
    assert 'node("h2","Ask DueSoon")' in source
    assert 'list("Urgent",data.urgent)' in source
    assert 'list("Upcoming",data.upcoming)' in source
    assert 'list("Missing or overdue"' in source
    assert 'list("Recently completed"' in source


def test_curated_shell_excludes_unsupported_odysseus_chrome() -> None:
    html = read("index.html")

    for legacy_id in ("chat-form", "message", "model-picker", "rag", "research", "group", "compare"):
        assert f'id="{legacy_id}"' not in html
    for legacy_label in ("Cookbook", "Deep Research", "Gallery", "Select model"):
        assert legacy_label not in html


def test_calendar_retains_controls_and_read_only_detail_behavior() -> None:
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

    for forbidden in ("localStorage", "sessionStorage", "serviceWorker", "X-API-Token", "/api/tools", "/api/execute"):
        assert forbidden not in source
    assert "/api/v1/dashboard/briefing" in source
    assert "/api/v1/dashboard/assistant" in source
    assert "/api/v1/dashboard/calendar" in source


def test_shell_does_not_surface_internal_canvas_freshness_badges() -> None:
    combined = read("index.html") + read("js/app.js")

    for forbidden in ("sidebar-freshness", 'id="freshness"', "Canvas fresh", "sidebarFresh", "fresh.textContent"):
        assert forbidden not in combined


def test_background_and_theme_behavior_is_explicit_and_bounded() -> None:
    html = read("index.html")
    login = read("login.html")
    shell = read("js/odysseus-shell.js")
    background = read("js/background.js")
    login_js = read("js/login.js")

    assert 'from "/static/js/theme.js"' in shell
    assert 'applyBgPattern("constellations")' in shell
    assert 'class="login-page bg-pattern-constellations"' in login
    assert "startConstellations" in login_js
    assert 'id = "constellations-canvas"' in background
    assert 'id="tool-theme-btn"' in html


def test_compact_navigation_uses_svg_icons_not_placeholder_glyphs() -> None:
    html = read("index.html")
    rail = html.split('<div class="icon-rail"', 1)[1].split("</div>\n\n  <nav", 1)[0]

    assert rail.count("<svg") >= 9
    for placeholder in ("⌂", "◇", "□", "✉", "♢", "▤", "◉", "▧", "⚙"):
        assert placeholder not in rail


def test_inherited_assets_are_included_in_production_build_context() -> None:
    dockerignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")

    assert "\nstatic/\n" not in f"\n{dockerignore}"
    assert "COPY --chown=duesoon:duesoon static ./static" in dockerfile


def test_login_restores_approved_split_surface_with_animation() -> None:
    html = read("login.html")

    assert 'href="/static/style.css"' in html
    assert 'class="login-shell"' in html
    assert 'class="login-brand"' in html
    assert 'class="login-card"' in html
    assert "Private academic workspace" in html
    assert "Welcome back" in html
    assert "Built on the Odysseus interface" in html
    assert "Canvas briefing and reminders" in html
