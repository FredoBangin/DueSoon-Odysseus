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
    assert ".duesoon-dashboard-grid" in css
    assert ".login-shell" in css
    for broad_selector in (
        "\nbody {",
        "\n.sidebar {",
        "\n.icon-rail {",
        "\n.chat-container {",
        "\n.admin-card {",
        "\n.cal-event-item {",
        "\n.cal-quickadd-row {",
        "\n.confirm-btn {",
    ):
        assert broad_selector not in css


def test_home_keeps_approved_two_column_briefing_and_embedded_assistant() -> None:
    source = read("js/views/home.js")

    for inherited_class in (
        "admin-card",
        "cal-event-item",
        "cal-event-dot",
        "cal-event-info",
        "cal-event-name",
        "cal-event-time",
        "cal-event-tag",
        "cal-quickadd-row",
        "cal-quickadd-input",
        "cal-quickadd-hint",
    ):
        assert inherited_class in source
    assert 'assignmentList("Urgent", data.urgent)' in source
    assert 'assignmentList("Work priority", data.upcoming, "priority")' in source
    assert "item.work_priority.band" in source
    assert 'assignmentList("Missing or overdue"' in source
    assert 'assignmentList("Recently completed"' in source
    assert 'node("button", "Ask")' not in source


def test_sidebar_uses_exact_odysseus_section_elements_and_animations() -> None:
    html = read("index.html")
    shell = read("js/odysseus-shell.js")

    assert '<span class="section-title" data-section-toggle="academic-items"' in html
    assert '<span class="section-title" data-section-toggle="retained-items"' in html
    assert html.count('class="section-icon"') >= 2
    assert html.count('class="sidebar-action-icon"') >= 10
    assert 'class="chat-container duesoon-workspace"' in html
    assert "welcome-active" not in html
    assert "section-just-expanded" in shell
    assert "section-just-collapsing" in shell


def test_settings_uses_native_odysseus_modal_tabs_and_controls() -> None:
    html = read("index.html")
    app = read("js/app.js")
    foundations = read("js/views/foundations.js")

    assert 'class="modal hidden" id="settings-modal"' in html
    assert 'class="modal-content settings-modal-content"' in html
    assert 'class="settings-layout"' in html
    assert 'class="settings-sidebar"' in html
    assert 'class="settings-panels" id="settings-content"' in html
    assert html.count("settings-nav-item") >= 2
    for inherited_class in (
        "admin-toggle-row",
        "admin-toggle-label",
        "admin-switch",
        "admin-slider",
        "settings-label",
        "settings-input",
        "confirm-btn confirm-btn-primary",
    ):
        assert inherited_class in foundations
    assert "renderSettings(settingsRoot)" in app
    assert "renderSettings(root)" not in app


def test_curated_shell_excludes_unsupported_odysseus_chrome() -> None:
    html = read("index.html")

    for legacy_id in ("chat-form", "message", "model-picker", "rag", "research", "group", "compare"):
        assert f'id="{legacy_id}"' not in html
    for legacy_label in ("Cookbook", "Deep Research", "Gallery", "Select model"):
        assert legacy_label not in html


def test_calendar_retains_controls_and_read_only_detail_behavior() -> None:
    source = read("js/views/calendar.js")
    css = read("css/app.css")

    for mode in ('"month"', '"week"', '"agenda"'):
        assert mode in source
    for label in ("Previous", "Today", "Next"):
        assert label in source
    assert "duesoon-calendar-detail" in source
    assert "Open in Canvas" in source
    assert 'new Set(["submitted","graded"])' in source
    assert "duesoon-calendar-complete" in source
    assert "text-decoration: line-through" in css
    assert all(word not in source for word in ("createEvent", "updateEvent", "deleteEvent"))
    assert "/api/v1/dashboard/assignments/${event.assignment_id}/planning" in source
    assert "Estimated minutes" in source
    assert "Percent complete" in source
    assert "confirm-btn confirm-btn-primary" in source


def test_gmail_can_be_saved_as_read_only_document_evidence() -> None:
    source = read("js/views/foundations.js")

    assert "Save inbox as evidence" in source
    assert "/api/v1/dashboard/gmail/sync" in source
    assert "DueSoon cannot send, delete, archive, or modify messages" in source
    assert "Raw bodies and signed download URLs are not exposed" in source


def test_review_surfaces_sanitized_academic_evidence_without_approval_controls() -> None:
    source = read("js/views/foundations.js")

    assert "value.evidence_items" in source
    assert "Academic evidence to review" in source
    assert "candidate_due_at" in source
    assert "Review assignment" in source
    assert "Raw source content stays private" in source
    assert "/api/v1/dashboard/assignments/" in source
    assert "/confirm-deadline" not in source
    assert "item.created_by" in source
    assert "item.audit" in source
    assert '["approved","rejected"].includes(item.status)' in source


def test_assistant_shows_safe_decision_trace_without_hidden_reasoning() -> None:
    source = read("js/views/assistant.js")

    assert "value.decision_trace" in source
    assert "How DueSoon answered" in source
    assert "Sources consulted" in source
    assert "Missing connections" in source
    assert "Policy versions" in source
    assert "chain-of-thought" not in source.casefold()


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
