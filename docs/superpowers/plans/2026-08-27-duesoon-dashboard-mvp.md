# DueSoon Dashboard MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a secure, responsive DueSoon web dashboard on the existing Azure service with owner login, real Canvas briefing data, a Canvas-style calendar, a deterministic assistant, notification history, and safe Review and Settings foundations while preserving live ntfy reminders.

**Architecture:** FastAPI remains the only active backend and serves a small dependency-free HTML/CSS/JavaScript application from `src/duesoon/web/static`. Browser-only APIs use revocable server-side sessions and CSRF protection; existing API-token automation stays separate. A Canvas-backed Effective Assignment projection and deterministic urgency service feed the dashboard, calendar, and assistant without making AI or browser state part of reminder delivery.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, Pydantic Settings 2.15.0, SQLAlchemy 2.0.52, SQLite, vanilla ES modules, Caddy 2.11.4, Docker Compose, pytest, Azure Linux VM, private ntfy.

**Spec:** `docs/superpowers/specs/2026-08-27-duesoon-dashboard-assistant-design.md`

## Global Constraints

- Read `DUESOON_CODEX_CONTEXT.md` and `AGENTS.md` before each implementation session.
- Use `effective_due_at` and `operational_due_at` for dashboard decisions; the MVP projection uses current Canvas `due_at` as explicit Canvas evidence until evidence fusion is implemented.
- Existing checkpoint crossing, database deduplication, dry-run behavior, immediate Canvas submission recheck, private ntfy delivery, and exactly one scheduler must not regress.
- Browser sessions, ntfy credentials, and the existing API token are separate security boundaries.
- The browser receives no API token, provider token, password hash, secret value, raw Canvas payload, or unrestricted HTML.
- Canvas assignments are read-only in this MVP.
- Gmail, Google Calendar, model-backed answers, durable correction learning, Notes, Memory, Documents, PWA, native apps, signup, billing, and multi-user tenancy remain disabled capabilities for separate plans.
- Production remains one Azure Linux VM with SQLite on `/mnt/duesoon/app`, Docker Compose, one Uvicorn worker, and one scheduler.
- Every task ends with focused tests and a commit. Do not run the quarantined inherited Odysseus test suite.
- Before production approval, run both a Codex Security diff scan and an active-runtime security scan; fix every confirmed finding or obtain explicit owner acceptance.

---

## File Map

### Authentication and application composition

- Modify `src/duesoon/config/settings.py`: add validated web, owner, origin, cookie, session, and login-throttle settings.
- Modify `src/duesoon/persistence/models.py`: add revocable `WebSession` and persistent `LoginAttempt` tables.
- Create `src/duesoon/auth/passwords.py`: encode and verify versioned stdlib scrypt password hashes; expose a stdin-only generator CLI.
- Create `src/duesoon/auth/service.py`: authenticate the owner, throttle failures, create/revoke/renew sessions, and verify CSRF.
- Create `src/duesoon/api/dependencies.py`: API-token and browser-session dependencies with no credential crossover.
- Create `src/duesoon/api/routes/auth.py`: login, session inspection, logout, and protected application document routes.
- Modify `src/duesoon/api/app.py`: construct services, include focused routers, mount `/assets`, and preserve scheduler lifecycle.

### Academic projections and dashboard APIs

- Create `src/duesoon/assignments/effective.py`: Canvas-baseline Effective Assignment projection.
- Create `src/duesoon/urgency/scoring.py`: exact urgency-v1 factors, thresholds, breakdown, and reasons.
- Create `src/duesoon/dashboard/briefing.py`: classify current academic state and freshness from persisted records.
- Create `src/duesoon/dashboard/calendar.py`: bounded date-range projection with stable course colors.
- Create `src/duesoon/dashboard/assistant.py`: deterministic intent classification and evidence-linked answers.
- Create `src/duesoon/api/dashboard_schemas.py`: all browser-safe request/response contracts.
- Create `src/duesoon/api/routes/dashboard.py`: authenticated read APIs plus deterministic assistant POST.

### Browser application

- Create `src/duesoon/web/static/login.html`: owner login document.
- Create `src/duesoon/web/static/index.html`: Odysseus-derived responsive navigation shell.
- Create `src/duesoon/web/static/css/app.css`: local design tokens, layout, status, calendar, and responsive rules.
- Create `src/duesoon/web/static/js/api.js`: same-origin fetch wrapper and in-memory CSRF handling.
- Create `src/duesoon/web/static/js/login.js`: login behavior with generic failures.
- Create `src/duesoon/web/static/js/app.js`: navigation, route state, session bootstrap, and degraded-state handling.
- Create `src/duesoon/web/static/js/views/home.js`: briefing cards.
- Create `src/duesoon/web/static/js/views/assistant.js`: deterministic conversation UI.
- Create `src/duesoon/web/static/js/views/calendar.js`: month, week, and agenda rendering.
- Create `src/duesoon/web/static/js/views/notifications.js`: reminder and delivery history.
- Create `src/duesoon/web/static/js/views/foundations.js`: Email, Review, Settings, Notes, Memory, and Documents capability views.

### Operations and verification

- Modify `.env.example` and `deploy/azure/production.env.example`: document non-secret web settings and empty secret values.
- Create `deploy/azure/configure-owner-login.sh`: safely create or rotate the web login without printing the password or hash.
- Modify `deploy/azure/provision-runtime.sh`: create separate ntfy and web credentials for fresh installs.
- Modify `deploy/azure/verify-runtime.sh`: verify login, authenticated briefing, anonymous denial, ntfy ACLs, and health.
- Modify `deploy/azure/Caddyfile`: route only DueSoon-owned paths to FastAPI and preserve all ntfy topic/subscription paths.
- Modify `tests/duesoon/test_runtime_manifest.py`: lock active routing and runtime boundaries.
- Create focused tests named in each task below.

---

### Task 1: Owner Passwords, Sessions, and Persistent Login Throttling

**Files:**
- Modify: `src/duesoon/config/settings.py`
- Modify: `src/duesoon/persistence/models.py`
- Create: `src/duesoon/auth/__init__.py`
- Create: `src/duesoon/auth/passwords.py`
- Create: `src/duesoon/auth/service.py`
- Test: `tests/duesoon/test_web_auth_service.py`
- Test: `tests/duesoon/test_settings.py`
- Test: `tests/duesoon/test_models.py`

**Interfaces:**
- Consumes: `DueSoonSettings`, `sessionmaker[Session]`, and the existing UTC-aware `utc_now()` convention.
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, encoded: str) -> bool`, `AuthService.login(username: str, password: str, client_key: str) -> CreatedSession`, `AuthService.authenticate(raw_token: str) -> SessionPrincipal | None`, `AuthService.revoke(raw_token: str) -> None`, and `AuthService.require_csrf(principal: SessionPrincipal, supplied: str) -> bool`.

- [ ] **Step 1: Write failing password, settings, schema, throttle, expiry, and revocation tests**

```python
def test_scrypt_hash_round_trip_and_rejects_wrong_password() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt.v1.32768.8.1.")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)

def test_production_web_requires_owner_credentials_and_https_origin() -> None:
    with pytest.raises(ValueError, match="web login requires"):
        DueSoonSettings(_env_file=None, environment="production", api_token="x", web_enabled=True)

def test_fifth_bad_login_is_rate_limited_but_valid_login_works_after_window(auth_fixture) -> None:
    auth, now_ref = auth_fixture
    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            auth.login("duesoon-owner", "wrong", "client-a")
    with pytest.raises(LoginRateLimited):
        auth.login("duesoon-owner", "correct", "client-a")
    now_ref[0] += timedelta(minutes=16)
    assert auth.login("duesoon-owner", "correct", "client-a").raw_token

def test_revoked_and_expired_sessions_do_not_authenticate(auth_fixture) -> None:
    auth, _now_ref = auth_fixture
    created = auth.login("duesoon-owner", "correct", "client-a")
    auth.revoke(created.raw_token)
    assert auth.authenticate(created.raw_token) is None
```

- [ ] **Step 2: Run the focused tests and confirm the new interfaces do not exist**

Run: `python -m pytest tests/duesoon/test_web_auth_service.py tests/duesoon/test_settings.py tests/duesoon/test_models.py -q`

Expected: FAIL on missing `src.duesoon.auth` and missing web settings/tables.

- [ ] **Step 3: Add exact web configuration and database records**

```python
web_enabled: bool = False
public_origin: str | None = None
owner_username: str = "duesoon-owner"
owner_password_hash: SecretStr | None = None
timezone: str = "America/New_York"
session_cookie_name: str = "duesoon_session"
session_ttl_minutes: int = Field(default=480, ge=15, le=10080)
login_max_attempts: int = Field(default=5, ge=3, le=20)
login_window_seconds: int = Field(default=900, ge=60, le=3600)

class WebSession(Base):
    __tablename__ = "web_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_key: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    successful: Mapped[bool] = mapped_column(Boolean, default=False)
```

Validation must require `owner_password_hash` plus an HTTPS `public_origin` when `environment == "production" and web_enabled`, normalize `public_origin` by removing its trailing slash, and reject any timezone that `zoneinfo.ZoneInfo` cannot load.

- [ ] **Step 4: Implement versioned scrypt and the authentication service**

```python
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 32768, 8, 1, 32

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
                            maxmem=64 * 1024 * 1024)
    return ".".join(("scrypt", "v1", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     _b64(salt), _b64(digest)))

@dataclass(frozen=True)
class CreatedSession:
    raw_token: str
    csrf_token: str
    expires_at: datetime

@dataclass(frozen=True)
class SessionPrincipal:
    session_id: int
    username: str
    csrf_token: str
    expires_at: datetime
```

Generate 32-byte random session tokens, persist only `sha256(raw_token)`, compare usernames and password digests without early-return timing differences, store every failed attempt, and prune attempts older than the configured window. Never log usernames, passwords, raw session tokens, CSRF tokens, hashes, or client addresses.

- [ ] **Step 5: Run the focused tests**

Run: `python -m pytest tests/duesoon/test_web_auth_service.py tests/duesoon/test_settings.py tests/duesoon/test_models.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the auth foundation**

```bash
git add src/duesoon/auth src/duesoon/config/settings.py src/duesoon/persistence/models.py tests/duesoon/test_web_auth_service.py tests/duesoon/test_settings.py tests/duesoon/test_models.py
git commit -m "feat: add secure owner session foundation"
```

---

### Task 2: Browser Authentication Routes and Security Middleware

**Files:**
- Create: `src/duesoon/api/dependencies.py`
- Create: `src/duesoon/api/routes/__init__.py`
- Create: `src/duesoon/api/routes/auth.py`
- Modify: `src/duesoon/api/app.py`
- Test: `tests/duesoon/test_web_auth_api.py`
- Test: `tests/duesoon/test_api.py`

**Interfaces:**
- Consumes: Task 1 `AuthService`, `CreatedSession`, and `SessionPrincipal`.
- Produces: `POST /api/v1/auth/login`, `GET /api/v1/auth/session`, `POST /api/v1/auth/logout`, `GET /login`, `GET /app`, `GET /app/{path:path}`, `require_browser_session(request: Request) -> SessionPrincipal`, and the existing `require_api_token` moved without behavior change.

- [ ] **Step 1: Write failing route-boundary tests**

```python
def test_login_sets_secure_http_only_strict_cookie_and_returns_csrf(client) -> None:
    response = client.post("/api/v1/auth/login", headers={"Origin": "https://due.test"},
                           json={"username": "duesoon-owner", "password": "correct"})
    assert response.status_code == 200
    assert response.json()["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie

def test_dashboard_api_rejects_api_token_without_browser_session(client) -> None:
    response = client.get("/api/v1/dashboard/briefing", headers={"X-API-Token": "api-secret"})
    assert response.status_code == 401

def test_logout_requires_csrf_and_revokes_session(authenticated_client) -> None:
    assert authenticated_client.post("/api/v1/auth/logout").status_code == 403
```

Also cover wrong credentials returning the same `401 {"detail":"invalid credentials"}` response, origin mismatch, missing Origin in production, expired session, `/app` redirecting unauthenticated users to `/login`, and API-token automation remaining accepted on `/api/v1/courses`.

- [ ] **Step 2: Run the auth API tests to verify failure**

Run: `python -m pytest tests/duesoon/test_web_auth_api.py tests/duesoon/test_api.py tests/duesoon/test_canvas_api.py -q`

Expected: FAIL because the auth router and browser dependency are missing.

- [ ] **Step 3: Implement strict browser dependencies and routes**

```python
SESSION_COOKIE = "duesoon_session"

def require_browser_session(request: Request) -> SessionPrincipal:
    token = request.cookies.get(request.app.state.settings.session_cookie_name)
    principal = request.app.state.auth.authenticate(token or "")
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal

def require_csrf(request: Request, principal: SessionPrincipal = Depends(require_browser_session)):
    supplied = request.headers.get("X-CSRF-Token", "")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(
        supplied, principal.csrf_token
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return principal
```

The login handler must validate `Origin == settings.public_origin`, derive a bounded `client_key` from the trusted request peer plus a fixed global bucket, call `AuthService.login`, set the cookie with `httponly=True`, `secure=settings.environment == "production"`, `samesite="strict"`, `path="/"`, and `max_age=session_ttl_minutes * 60`, then return only username, expiry, and CSRF token. All auth responses set `Cache-Control: no-store`.

- [ ] **Step 4: Refactor app composition without changing scheduler ownership**

```python
runtime_auth = AuthService(runtime_settings, runtime_sessions)
application.state.auth = runtime_auth
application.include_router(build_auth_router(runtime_settings))

# Existing lifecycle remains single-owner:
if runtime_scheduler is not None:
    runtime_scheduler.start()
try:
    yield
finally:
    if runtime_scheduler is not None:
        await runtime_scheduler.stop()
```

Keep `/health/live` and `/health/ready` public, keep existing API-token routes unchanged, and register no inherited Odysseus route.

- [ ] **Step 5: Run auth and existing API regression tests**

Run: `python -m pytest tests/duesoon/test_web_auth_api.py tests/duesoon/test_api.py tests/duesoon/test_canvas_api.py tests/duesoon/test_scheduler.py -q`

Expected: PASS.

- [ ] **Step 6: Commit browser authentication**

```bash
git add src/duesoon/api/app.py src/duesoon/api/dependencies.py src/duesoon/api/routes tests/duesoon/test_web_auth_api.py tests/duesoon/test_api.py
git commit -m "feat: protect dashboard with owner login"
```

---

### Task 3: Effective Assignment Projection and Urgency-v1

**Files:**
- Create: `src/duesoon/assignments/__init__.py`
- Create: `src/duesoon/assignments/effective.py`
- Create: `src/duesoon/urgency/__init__.py`
- Create: `src/duesoon/urgency/scoring.py`
- Test: `tests/duesoon/test_effective_projection.py`
- Test: `tests/duesoon/test_urgency.py`

**Interfaces:**
- Consumes: persisted `Assignment`, `Course`, and `Submission` objects.
- Produces: `project_canvas_assignment(assignment: Assignment) -> EffectiveAssignment`, `score_assignment(item: EffectiveAssignment, all_items: Sequence[EffectiveAssignment], now: datetime, earlier_move_hours: float | None = None) -> UrgencyBreakdown`.

- [ ] **Step 1: Write failing projection and every urgency-boundary test**

```python
def test_canvas_projection_names_deadline_source_explicitly(assignment) -> None:
    item = project_canvas_assignment(assignment)
    assert item.effective_due_at == assignment.canvas_due_at
    assert item.operational_due_at == assignment.canvas_due_at
    assert item.deadline_status == "resolved"
    assert item.deadline_confidence == "high"
    assert item.deadline_source_summary == "Current Canvas assignment deadline"

@pytest.mark.parametrize(("remaining", "points"), [
    (timedelta(days=8), 0), (timedelta(days=7), 8),
    (timedelta(days=3), 15), (timedelta(hours=24), 25),
    (timedelta(hours=12), 32), (timedelta(hours=6), 42),
    (timedelta(hours=1), 50), (timedelta(minutes=15), 55),
    (timedelta(seconds=-1), 55),
])
def test_time_factor_exact_boundaries(remaining: timedelta, points: int) -> None:
    assert time_remaining_score(remaining) == points
```

Add tests for every points bucket, cluster counts 0 through 4+, earlier-move scores 0/3/6/10, missing +10, late +5, completed override to zero, 105 clamped to 100, and LOW/MEDIUM/HIGH/CRITICAL thresholds.

- [ ] **Step 2: Run projection and scoring tests to verify failure**

Run: `python -m pytest tests/duesoon/test_effective_projection.py tests/duesoon/test_urgency.py -q`

Expected: FAIL on missing packages.

- [ ] **Step 3: Implement immutable projection and exact score contract**

```python
@dataclass(frozen=True)
class EffectiveAssignment:
    assignment_id: int
    canvas_assignment_id: str
    course_id: int
    course_name: str
    canonical_title: str
    assignment_url: str | None
    canvas_due_at: datetime | None
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    deadline_status: Literal["resolved", "unknown"]
    deadline_confidence: Literal["high", "low"]
    deadline_source_summary: str
    points_possible: float | None
    submission_status: str
    submitted_at: datetime | None

@dataclass(frozen=True)
class UrgencyBreakdown:
    time_score: int
    value_score: int
    workload_score: int
    due_date_change_score: int
    submission_score: int
    raw_score: int
    total: int
    level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    reasons: tuple[str, ...]
    config_version: str = "urgency-v1"
```

Unknown deadlines return time score zero and a reason stating that no precise deadline is available. All timestamps must be normalized to UTC before comparison; completed items return total zero regardless of other factors.

- [ ] **Step 4: Run all projection and scoring tests**

Run: `python -m pytest tests/duesoon/test_effective_projection.py tests/duesoon/test_urgency.py -q`

Expected: PASS.

- [ ] **Step 5: Commit deterministic academic projection**

```bash
git add src/duesoon/assignments src/duesoon/urgency tests/duesoon/test_effective_projection.py tests/duesoon/test_urgency.py
git commit -m "feat: project effective assignments and urgency"
```

---

### Task 4: Academic Briefing Service and Authenticated Home API

**Files:**
- Create: `src/duesoon/dashboard/__init__.py`
- Create: `src/duesoon/dashboard/briefing.py`
- Create: `src/duesoon/api/dashboard_schemas.py`
- Create: `src/duesoon/api/routes/dashboard.py`
- Modify: `src/duesoon/api/app.py`
- Test: `tests/duesoon/test_dashboard_briefing.py`

**Interfaces:**
- Consumes: Task 3 projections/scoring, `Session`, `SyncRun`, `ReminderEvent`, `NotificationDelivery`, and `SchedulerState`.
- Produces: `BriefingService.snapshot(now: datetime | None = None) -> BriefingSnapshot` and browser-session-only `GET /api/v1/dashboard/briefing`.

- [ ] **Step 1: Write failing populated, empty, stale, authorization, and redaction tests**

```python
def test_briefing_groups_real_persisted_assignments(authenticated_client, seeded_db) -> None:
    body = authenticated_client.get("/api/v1/dashboard/briefing").json()
    assert [item["title"] for item in body["urgent"]] == ["Lab 4"]
    assert body["missing"][0]["submission_status"] == "missing"
    assert body["freshness"]["canvas_status"] == "fresh"
    assert body["limitations"] == ["Deadline evidence is currently Canvas-only"]

def test_briefing_never_returns_raw_payloads_or_secrets(authenticated_client, seeded_db) -> None:
    text = authenticated_client.get("/api/v1/dashboard/briefing").text
    assert "raw_payload" not in text and "canvas-secret" not in text
```

Classify urgent as HIGH/CRITICAL incomplete work, upcoming as the next ten incomplete items within 14 days, overdue by `operational_due_at < now`, missing from normalized state, and recently completed as submitted/graded records observed within seven days. Use the latest successful `SyncRun` for freshness; older than two scheduler intervals is stale.

- [ ] **Step 2: Run the briefing tests to verify failure**

Run: `python -m pytest tests/duesoon/test_dashboard_briefing.py -q`

Expected: FAIL because the service and route do not exist.

- [ ] **Step 3: Implement one query pass and typed browser-safe output**

```python
@dataclass(frozen=True)
class BriefingSnapshot:
    generated_at: datetime
    timezone: str
    urgent: tuple[BriefingAssignment, ...]
    upcoming: tuple[BriefingAssignment, ...]
    overdue: tuple[BriefingAssignment, ...]
    missing: tuple[BriefingAssignment, ...]
    completed_recently: tuple[BriefingAssignment, ...]
    deadline_changes: tuple[DeadlineChange, ...]
    reminder_counts: dict[str, int]
    freshness: Freshness
    questions: tuple[str, ...]
    limitations: tuple[str, ...]
```

Load assignments with `selectinload(Assignment.course, Assignment.submission)`, project all records once, compute cluster scores from the complete projected tuple, and serialize only allow-listed fields. Compare the two newest `AssignmentSnapshot` records per assignment to report due-date changes without exposing normalized payload JSON.

- [ ] **Step 4: Register the dashboard router with browser auth only**

```python
router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_browser_session)])

@router.get("/briefing", response_model=BriefingResponse)
def briefing(request: Request) -> BriefingResponse:
    return BriefingResponse.model_validate(
        request.app.state.briefing.snapshot(), from_attributes=True
    )

```

- [ ] **Step 5: Run briefing plus Canvas/reminder regression tests**

Run: `python -m pytest tests/duesoon/test_dashboard_briefing.py tests/duesoon/test_canvas_api.py tests/duesoon/test_reminders.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the briefing API**

```bash
git add src/duesoon/dashboard src/duesoon/api/dashboard_schemas.py src/duesoon/api/routes/dashboard.py src/duesoon/api/app.py tests/duesoon/test_dashboard_briefing.py
git commit -m "feat: expose academic dashboard briefing"
```

---

### Task 5: Canvas-Style Calendar Projection API

**Files:**
- Create: `src/duesoon/dashboard/calendar.py`
- Modify: `src/duesoon/api/dashboard_schemas.py`
- Modify: `src/duesoon/api/routes/dashboard.py`
- Test: `tests/duesoon/test_dashboard_calendar.py`

**Interfaces:**
- Consumes: `EffectiveAssignment`, fixed `COURSE_COLORS`, configured `DUESOON_TIMEZONE`, and browser session dependency.
- Produces: `CalendarService.events(start: date, end: date) -> tuple[CalendarEvent, ...]` and `GET /api/v1/dashboard/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD`.

- [ ] **Step 1: Write failing timezone, color, range, status, and auth tests**

```python
def test_calendar_projects_due_date_in_student_timezone(authenticated_client, seeded_db) -> None:
    response = authenticated_client.get(
        "/api/v1/dashboard/calendar?start=2026-08-31&end=2026-09-07"
    )
    event = response.json()["events"][0]
    assert event["local_date"] == "2026-08-31"
    assert event["source"] == "canvas"
    assert event["read_only"] is True
    assert event["status"] in {"upcoming", "overdue", "missing", "submitted", "graded"}

def test_calendar_rejects_inverted_or_over_93_day_range(authenticated_client) -> None:
    assert authenticated_client.get("/api/v1/dashboard/calendar?start=2026-10-01&end=2026-09-01").status_code == 422
```

- [ ] **Step 2: Run calendar tests to verify failure**

Run: `python -m pytest tests/duesoon/test_dashboard_calendar.py -q`

Expected: FAIL on missing calendar route.

- [ ] **Step 3: Implement a bounded read-only calendar projection**

```python
COURSE_COLORS = ("#0b84f3", "#8b5cf6", "#e4553d", "#1b9e77", "#d97706", "#db2777")

def course_color(canvas_course_id: str) -> str:
    index = int(hashlib.sha256(canvas_course_id.encode()).hexdigest()[:8], 16)
    return COURSE_COLORS[index % len(COURSE_COLORS)]

@dataclass(frozen=True)
class CalendarEvent:
    id: str
    assignment_id: int
    title: str
    course_name: str
    starts_at: datetime
    local_date: date
    color: str
    status: str
    urgency_level: str
    source: Literal["canvas"] = "canvas"
    read_only: bool = True
    external_url: str | None = None
```

Use `ZoneInfo(settings.timezone)` for local-date projection, reject spans beyond 93 days, include only records with precise operational deadlines inside the half-open local interval, and never expose mutation methods.

- [ ] **Step 4: Run calendar and timezone tests**

Run: `python -m pytest tests/duesoon/test_dashboard_calendar.py tests/duesoon/test_canvas_normalize.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the calendar API**

```bash
git add src/duesoon/dashboard/calendar.py src/duesoon/api/dashboard_schemas.py src/duesoon/api/routes/dashboard.py tests/duesoon/test_dashboard_calendar.py
git commit -m "feat: add Canvas-style calendar projection"
```

---

### Task 6: Deterministic Dashboard Assistant

**Files:**
- Create: `src/duesoon/dashboard/assistant.py`
- Modify: `src/duesoon/api/dashboard_schemas.py`
- Modify: `src/duesoon/api/routes/dashboard.py`
- Test: `tests/duesoon/test_dashboard_assistant.py`

**Interfaces:**
- Consumes: `BriefingService.snapshot()`.
- Produces: `DeterministicAssistant.answer(question: str, snapshot: BriefingSnapshot) -> AssistantAnswer` and `POST /api/v1/dashboard/assistant` guarded by browser session plus CSRF.

- [ ] **Step 1: Write failing intent, evidence, ambiguity, length, CSRF, and privacy tests**

```python
@pytest.mark.parametrize(("question", "intent"), [
    ("Any updates?", "status_update"),
    ("What is due next?", "due_next"),
    ("What am I missing?", "missing_work"),
    ("Did I submit everything?", "completion_check"),
])
def test_supported_questions_return_deterministic_answers(
    assistant: DeterministicAssistant,
    snapshot: BriefingSnapshot,
    question: str,
    intent: str,
) -> None:
    answer = assistant.answer(question, snapshot)
    assert answer.intent == intent
    assert answer.mode == "deterministic"
    assert all(item.href.startswith("/app/") or item.href.startswith("https://")
               for item in answer.evidence)

def test_unknown_question_lists_supported_prompts_without_guessing(
    assistant: DeterministicAssistant,
    snapshot: BriefingSnapshot,
) -> None:
    answer = assistant.answer("Predict my grade", snapshot)
    assert answer.intent == "unsupported"
    assert answer.confidence == "unknown"
```

Also assert the route rejects a body over 500 characters, rejects API-token-only access, rejects missing/wrong CSRF, and never returns raw payloads or secret configuration.

- [ ] **Step 2: Run assistant tests to verify failure**

Run: `python -m pytest tests/duesoon/test_dashboard_assistant.py -q`

Expected: FAIL on missing assistant module/route.

- [ ] **Step 3: Implement explicit intent rules and evidence-linked responses**

```python
SUPPORTED_PROMPTS = (
    "Any updates?", "What is due next?", "What am I missing?", "Did I submit everything?"
)

@dataclass(frozen=True)
class AssistantAnswer:
    mode: Literal["deterministic"]
    intent: Literal["status_update", "due_next", "missing_work", "completion_check", "unsupported"]
    answer: str
    confidence: Literal["high", "unknown"]
    evidence: tuple[EvidenceLink, ...]
    generated_at: datetime
    data_freshness: str
```

Normalize Unicode, lowercase, and collapse whitespace. Match only allow-listed phrase/keyword rules. Build answer sentences from snapshot fields, include at most ten evidence links, escape nothing manually in Python because JSON remains structured, and return the supported prompt list for unsupported requests. Do not call any model provider.

Register the state-changing assistant request with explicit browser-session and CSRF dependencies:

```python
@router.post(
    "/assistant",
    response_model=AssistantResponse,
    dependencies=[Depends(require_csrf)],
)
def assistant(request: Request, payload: AssistantRequest) -> AssistantResponse:
    snapshot = request.app.state.briefing.snapshot()
    return AssistantResponse.model_validate(
        request.app.state.assistant.answer(payload.question, snapshot),
        from_attributes=True,
    )
```

- [ ] **Step 4: Run assistant and auth tests**

Run: `python -m pytest tests/duesoon/test_dashboard_assistant.py tests/duesoon/test_web_auth_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit deterministic assistant behavior**

```bash
git add src/duesoon/dashboard/assistant.py src/duesoon/api/dashboard_schemas.py src/duesoon/api/routes/dashboard.py tests/duesoon/test_dashboard_assistant.py
git commit -m "feat: add deterministic dashboard assistant"
```

---

### Task 7: Notification History, Review Foundation, and Safe Settings Status

**Files:**
- Modify: `src/duesoon/dashboard/briefing.py`
- Modify: `src/duesoon/api/dashboard_schemas.py`
- Modify: `src/duesoon/api/routes/dashboard.py`
- Test: `tests/duesoon/test_dashboard_secondary_api.py`

**Interfaces:**
- Consumes: `ReminderEvent`, `NotificationDelivery`, `SchedulerState`, and non-secret booleans from `DueSoonSettings`.
- Produces: `GET /api/v1/dashboard/notifications?limit=50`, `GET /api/v1/dashboard/review`, and `GET /api/v1/dashboard/settings`.

- [ ] **Step 1: Write failing ordering, limit, redaction, disabled-capability, and authorization tests**

```python
def test_notification_history_is_newest_first_and_redacted(authenticated_client, seeded_db) -> None:
    body = authenticated_client.get("/api/v1/dashboard/notifications?limit=20").json()
    assert body["items"][0]["status"] in {"sent", "dry_run", "suppressed_submission", "failed"}
    assert "ntfy_token" not in json.dumps(body).lower()

def test_settings_returns_status_not_secret_values(authenticated_client) -> None:
    body = authenticated_client.get("/api/v1/dashboard/settings").json()
    assert body["canvas"]["configured"] is True
    assert set(body["canvas"]) == {"configured", "status"}
    assert body["features"]["gmail"] == "deferred"
```

Review must return `items=[]`, `enabled=False`, and explanatory copy that learning proposals are unavailable until the learning phase. Settings must list Canvas, ntfy, scheduler, dry-run, model provider, Gmail, Google Calendar, Notes, Memory, and Documents using only booleans/status labels.

- [ ] **Step 2: Run the secondary API tests to verify failure**

Run: `python -m pytest tests/duesoon/test_dashboard_secondary_api.py -q`

Expected: FAIL on missing routes.

- [ ] **Step 3: Implement bounded history queries and explicit capability states**

```python
@router.get("/notifications", response_model=NotificationHistoryResponse)
def notification_history(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    return request.app.state.briefing.notification_history(limit=limit)

DEFERRED_FEATURES = {
    "model_assistant": "deferred", "gmail": "deferred", "google_calendar": "deferred",
    "notes": "deferred", "memory": "deferred", "documents": "deferred",
}
```

Use explicit response schemas. Return rendered reminder title/body because they are already notification audit records, but omit ntfy topic, provider request details, raw Canvas payloads, API tokens, hashes, and internal exception text.

- [ ] **Step 4: Run secondary API and notification regressions**

Run: `python -m pytest tests/duesoon/test_dashboard_secondary_api.py tests/duesoon/test_notification_api.py tests/duesoon/test_reminders.py -q`

Expected: PASS.

- [ ] **Step 5: Commit dashboard support APIs**

```bash
git add src/duesoon/dashboard/briefing.py src/duesoon/api/dashboard_schemas.py src/duesoon/api/routes/dashboard.py tests/duesoon/test_dashboard_secondary_api.py
git commit -m "feat: expose dashboard activity and capability status"
```

---

### Task 8: Odysseus-Derived Web Shell and Login Experience

**Files:**
- Create: `src/duesoon/web/__init__.py`
- Create: `src/duesoon/web/static/login.html`
- Create: `src/duesoon/web/static/index.html`
- Create: `src/duesoon/web/static/css/app.css`
- Create: `src/duesoon/web/static/js/api.js`
- Create: `src/duesoon/web/static/js/login.js`
- Create: `src/duesoon/web/static/js/app.js`
- Modify: `src/duesoon/api/routes/auth.py`
- Modify: `src/duesoon/api/app.py`
- Test: `tests/duesoon/test_web_assets.py`

**Interfaces:**
- Consumes: Task 2 auth endpoints and static files packaged beneath `src/duesoon` by the existing Dockerfile.
- Produces: `/login`, `/app`, `/app/{path:path}`, `/assets/*`, `api.bootstrapSession()`, `api.get(path)`, and `api.post(path, body)`.

- [ ] **Step 1: Write failing page, asset, navigation, cache, and unsafe-pattern tests**

```python
def test_authenticated_app_contains_approved_navigation(authenticated_client) -> None:
    html = authenticated_client.get("/app").text
    for label in ("Home", "Assistant", "Calendar", "Email", "Notifications", "Review", "Settings"):
        assert f">{label}<" in html

def test_frontend_does_not_persist_secrets_or_register_service_worker() -> None:
    javascript = "\n".join(path.read_text() for path in JS_ROOT.glob("**/*.js"))
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert "serviceWorker" not in javascript
    assert "X-API-Token" not in javascript
```

Also assert unauthenticated `/app` redirects to `/login`, assets contain no template-secret substitutions, HTML responses use `Cache-Control: no-store`, static assets set `X-Content-Type-Options: nosniff`, and inherited `/static/index.html` is not served.

- [ ] **Step 2: Run web asset tests to verify failure**

Run: `python -m pytest tests/duesoon/test_web_assets.py -q`

Expected: FAIL because the focused web app is absent.

- [ ] **Step 3: Build the static shell and same-origin API client**

```javascript
let csrfToken = "";

export async function bootstrapSession() {
  const response = await fetch("/api/v1/auth/session", { credentials: "same-origin", cache: "no-store" });
  if (response.status === 401) { window.location.replace("/login"); return null; }
  const session = await response.json();
  csrfToken = session.csrf_token;
  return session;
}

export async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(body),
  });
  if (response.status === 401) window.location.replace("/login");
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
```

The login page sends username/password only to `/api/v1/auth/login`, clears the password input immediately, stores the returned CSRF token only in module memory, and displays one generic error message. The app shell uses semantic `<nav>`, `<main>`, buttons, status regions, and static inline SVG icons; it does not use remote scripts, remote fonts, or inline executable script.

- [ ] **Step 4: Add Odysseus-derived visual tokens without importing legacy runtime code**

```css
:root {
  --bg: #0b0d12; --surface: #131722; --surface-2: #1a2030;
  --text: #f4f7fb; --muted: #9ba7b7; --border: #293244;
  --accent: #ee5d4f; --success: #35b779; --warning: #e4a11b; --danger: #ef5350;
  --sidebar-width: 248px; --radius: 14px;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
}
@media (max-width: 760px) {
  .sidebar { position: fixed; inset: auto 0 0; width: 100%; height: 64px; }
  .workspace { margin-left: 0; padding-bottom: 76px; }
  .nav-label { display: none; }
}
```

Copy only the interaction ideas and local visual feel from inherited Odysseus. Do not import its `app.js`, generic agent routes, service worker, local-storage configuration, email composer, calendar writeback, or tool code.

- [ ] **Step 5: Mount assets and run Python plus JavaScript syntax checks**

Run: `python -m pytest tests/duesoon/test_web_assets.py tests/duesoon/test_web_auth_api.py -q`

Run: `node --check src/duesoon/web/static/js/api.js; node --check src/duesoon/web/static/js/login.js; node --check src/duesoon/web/static/js/app.js`

Expected: all PASS/exit 0.

- [ ] **Step 6: Commit the secure web shell**

```bash
git add src/duesoon/web src/duesoon/api/routes/auth.py src/duesoon/api/app.py tests/duesoon/test_web_assets.py
git commit -m "feat: add DueSoon web shell"
```

---

### Task 9: Home and Deterministic Assistant Views

**Files:**
- Create: `src/duesoon/web/static/js/views/home.js`
- Create: `src/duesoon/web/static/js/views/assistant.js`
- Modify: `src/duesoon/web/static/js/app.js`
- Modify: `src/duesoon/web/static/css/app.css`
- Test: `tests/duesoon/test_web_home_assistant.py`

**Interfaces:**
- Consumes: `GET /api/v1/dashboard/briefing` and `POST /api/v1/dashboard/assistant`.
- Produces: `renderHome(root, briefing)`, `renderAssistant(root)`, and in-memory assistant exchanges for the active page session.

- [ ] **Step 1: Write failing static safety and API integration tests**

```python
def test_home_and_assistant_modules_use_text_nodes_for_server_data() -> None:
    source = read("src/duesoon/web/static/js/views/home.js") + read(
        "src/duesoon/web/static/js/views/assistant.js"
    )
    assert ".innerHTML" not in source
    assert "textContent" in source

def test_assistant_form_uses_csrf_api_client() -> None:
    source = read("src/duesoon/web/static/js/views/assistant.js")
    assert 'post("/api/v1/dashboard/assistant"' in source
```

- [ ] **Step 2: Run the view tests to verify failure**

Run: `python -m pytest tests/duesoon/test_web_home_assistant.py -q`

Expected: FAIL because view modules are missing.

- [ ] **Step 3: Implement accessible briefing cards and evidence links**

```javascript
function text(tag, value, className = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = value;
  return node;
}

export function safeExternalLink(url, label) {
  const parsed = new URL(url, window.location.origin);
  if (!['https:', 'http:'].includes(parsed.protocol)) return text('span', label);
  const link = text('a', label);
  link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}
```

Home renders freshness first, then urgent, upcoming, overdue/missing, changes, reminder activity, and the assistant input. Empty data produces “Canvas is connected, but no active assignments were found” or the specific freshness error, never a blank panel.

- [ ] **Step 4: Implement bounded in-memory assistant conversation**

Use only DOM construction and `textContent`. Disable submit while a request is active, limit the input to 500 characters in HTML and JavaScript, show `mode`, `confidence`, data freshness, and clickable evidence for each response, and offer the four supported prompt chips. Do not persist questions or answers to browser storage.

- [ ] **Step 5: Run view, API, and JavaScript syntax tests**

Run: `python -m pytest tests/duesoon/test_web_home_assistant.py tests/duesoon/test_dashboard_briefing.py tests/duesoon/test_dashboard_assistant.py -q`

Run: `node --check src/duesoon/web/static/js/views/home.js; node --check src/duesoon/web/static/js/views/assistant.js`

Expected: all PASS/exit 0.

- [ ] **Step 6: Commit Home and Assistant views**

```bash
git add src/duesoon/web/static/js/views/home.js src/duesoon/web/static/js/views/assistant.js src/duesoon/web/static/js/app.js src/duesoon/web/static/css/app.css tests/duesoon/test_web_home_assistant.py
git commit -m "feat: render academic home and assistant"
```

---

### Task 10: Calendar, Notifications, Review, Settings, and Deferred Tabs

**Files:**
- Create: `src/duesoon/web/static/js/views/calendar.js`
- Create: `src/duesoon/web/static/js/views/notifications.js`
- Create: `src/duesoon/web/static/js/views/foundations.js`
- Modify: `src/duesoon/web/static/js/app.js`
- Modify: `src/duesoon/web/static/css/app.css`
- Test: `tests/duesoon/test_web_dashboard_views.py`

**Interfaces:**
- Consumes: calendar, notification, review, and settings APIs from Tasks 5 and 7.
- Produces: `renderCalendar(root, initialView)`, `renderNotifications(root)`, `renderReview(root)`, `renderSettings(root)`, and `renderDeferredFeature(root, feature)`.

- [ ] **Step 1: Write failing view-mode, read-only, disabled-feature, and safe-render tests**

```python
def test_calendar_has_canvas_style_modes_and_no_write_controls() -> None:
    source = read("src/duesoon/web/static/js/views/calendar.js")
    assert all(mode in source for mode in ('"month"', '"week"', '"agenda"'))
    assert "createEvent" not in source and "updateEvent" not in source and "deleteEvent" not in source

def test_retained_tabs_are_visible_but_explicitly_disabled() -> None:
    source = read("src/duesoon/web/static/js/views/foundations.js")
    for feature in ("Email", "Notes", "Memory", "Documents"):
        assert feature in source
    assert "Available after the web MVP is stable" in source
```

- [ ] **Step 2: Run secondary view tests to verify failure**

Run: `python -m pytest tests/duesoon/test_web_dashboard_views.py -q`

Expected: FAIL because the modules are absent.

- [ ] **Step 3: Implement month, week, and agenda projections**

```javascript
const VIEWS = new Set(["month", "week", "agenda"]);

export async function renderCalendar(root, initialView = "month") {
  let view = VIEWS.has(initialView) ? initialView : "month";
  let anchor = new Date();
  const refresh = async () => {
    const { start, end } = rangeFor(view, anchor);
    const data = await get(`/api/v1/dashboard/calendar?start=${start}&end=${end}`);
    drawCalendar(root, view, anchor, data.events);
  };
  bindCalendarControls(root, { setView: value => { view = value; refresh(); },
                               move: amount => { anchor = moveAnchor(anchor, view, amount); refresh(); },
                               today: () => { anchor = new Date(); refresh(); } });
  await refresh();
}
```

Month uses a seven-column grid, week uses seven day columns with time labels, and agenda groups chronologically by local date. Each assignment shows course color, title, due time, status, and urgency; selecting it opens a read-only detail drawer with a validated Canvas HTTPS link.

- [ ] **Step 4: Implement history and capability panels**

Notifications group sent, dry-run, suppressed, and failed outcomes and show exact audit reasons. Review shows an empty disabled state explaining approval/edit/reject/undo will arrive with learning. Settings shows configuration status only. Email shows Gmail read-only integration as deferred. Notes, Memory, and Documents remain visible under “Retained from Odysseus” and disabled.

- [ ] **Step 5: Run all view and JavaScript syntax tests**

Run: `python -m pytest tests/duesoon/test_web_dashboard_views.py tests/duesoon/test_dashboard_calendar.py tests/duesoon/test_dashboard_secondary_api.py -q`

Run: `node --check src/duesoon/web/static/js/views/calendar.js; node --check src/duesoon/web/static/js/views/notifications.js; node --check src/duesoon/web/static/js/views/foundations.js`

Expected: all PASS/exit 0.

- [ ] **Step 6: Commit the remaining dashboard views**

```bash
git add src/duesoon/web/static/js/views/calendar.js src/duesoon/web/static/js/views/notifications.js src/duesoon/web/static/js/views/foundations.js src/duesoon/web/static/js/app.js src/duesoon/web/static/css/app.css tests/duesoon/test_web_dashboard_views.py
git commit -m "feat: complete dashboard MVP views"
```

---

### Task 11: Production Routing, Credential Rotation, and Runtime Verification

**Files:**
- Modify: `.env.example`
- Modify: `deploy/azure/production.env.example`
- Create: `deploy/azure/configure-owner-login.sh`
- Modify: `deploy/azure/provision-runtime.sh`
- Modify: `deploy/azure/verify-runtime.sh`
- Modify: `deploy/azure/Caddyfile`
- Modify: `tests/duesoon/test_runtime_manifest.py`
- Create: `tests/duesoon/test_azure_dashboard_runtime.py`

**Interfaces:**
- Consumes: password generator CLI, existing `/etc/duesoon/duesoon.env`, `/etc/duesoon/owner-credentials.env`, Compose, and the current public Azure hostname.
- Produces: isolated routing for DueSoon web/API paths, preserved ntfy fallback routing, and repeatable login rotation/verification scripts.

- [ ] **Step 1: Write failing manifest and script contract tests**

```python
def test_caddy_routes_dashboard_but_leaves_topic_paths_to_ntfy() -> None:
    caddy = read("deploy/azure/Caddyfile")
    assert "@duesoon path / /login /app* /assets/* /api/* /health/*" in caddy
    assert "handle @duesoon" in caddy
    assert caddy.index("handle @duesoon") < caddy.index("reverse_proxy ntfy:80")

def test_owner_login_configuration_never_accepts_password_as_argument() -> None:
    script = read("deploy/azure/configure-owner-login.sh")
    assert "read -r -s" in script
    assert "hash-stdin" in script
    assert "DUESOON_OWNER_PASSWORD_HASH" in script
```

Also assert the runtime environment examples include web enablement, public origin, username, empty password hash, timezone, and no populated secret. Verify Caddy includes CSP, frame denial, permissions policy, HSTS, no-sniff, and no-referrer headers.

- [ ] **Step 2: Run runtime tests to verify failure**

Run: `python -m pytest tests/duesoon/test_runtime_manifest.py tests/duesoon/test_azure_dashboard_runtime.py -q`

Expected: FAIL on missing routes, headers, web settings, and rotation script.

- [ ] **Step 3: Implement exact Caddy ownership and headers**

```caddyfile
@duesoon path / /login /app* /assets/* /api/* /health/* /docs* /redoc* /openapi.json
handle @duesoon {
    header {
        Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()"
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
    }
    reverse_proxy duesoon:7000
}
handle {
    reverse_proxy ntfy:80
}
```

This preserves ntfy topic paths such as `/<topic>/json`, `/<topic>/sse`, `/<topic>/ws`, publishing paths, `/v1/health`, and iPhone subscriptions because only the explicit DueSoon matcher is diverted.

- [ ] **Step 4: Add secret-safe web credential provisioning and rotation**

`configure-owner-login.sh` must run as root, take only an optional username argument, prompt twice with `read -r -s`, pass the password to `python3 -m src.duesoon.auth.passwords hash-stdin` over stdin, write a mode-0600 temporary file in `/etc/duesoon`, preserve unrelated environment lines, atomically replace `DUESOON_OWNER_USERNAME`, `DUESOON_OWNER_PASSWORD_HASH`, `DUESOON_WEB_ENABLED=true`, and `DUESOON_PUBLIC_ORIGIN=https://$DUESOON_PUBLIC_HOST`, then remove plaintext shell variables. It must never use `set -x`, print the password/hash, or put either in process arguments.

Fresh provisioning creates separate random ntfy and web passwords, stores only the web hash in `duesoon.env`, and writes the one-time web password under `WEB_USERNAME`/`WEB_PASSWORD` in the already-protected `owner-credentials.env`.

- [ ] **Step 5: Extend runtime verification without leaking credentials**

The verifier must:

1. confirm `/health/ready` is 200;
2. confirm anonymous `/app` redirects and anonymous briefing returns 401;
3. send login JSON over stdin to `curl --json @-` and store cookies/response in mode-0600 temporary files;
4. extract the CSRF token without printing it;
5. confirm authenticated briefing is 200;
6. confirm wrong CSRF logout is 403 and correct CSRF logout is 200;
7. confirm anonymous ntfy topic polling is 401/403; and
8. print status codes and counts only.

- [ ] **Step 6: Run runtime tests, shell syntax, and Compose validation**

Run: `python -m pytest tests/duesoon/test_runtime_manifest.py tests/duesoon/test_azure_dashboard_runtime.py -q`

Run: `bash -n deploy/azure/configure-owner-login.sh deploy/azure/provision-runtime.sh deploy/azure/verify-runtime.sh`

Run: `docker compose -f deploy/azure/docker-compose.production.yml --env-file deploy/azure/production.env.example config --quiet`

Expected: all PASS/exit 0. If local Docker is unavailable, record only the Compose validation as locally blocked and run it on Azure before deployment.

- [ ] **Step 7: Commit production integration**

```bash
git add .env.example deploy/azure tests/duesoon/test_runtime_manifest.py tests/duesoon/test_azure_dashboard_runtime.py
git commit -m "ops: route and verify secure dashboard"
```

---

### Task 12: Focused Regression, Browser Verification, Codex Security Gate, and Azure Release

**Files:**
- Create: `docs/operations/dashboard-mvp-release.md`
- Modify only when findings require fixes: files from Tasks 1–11

**Interfaces:**
- Consumes: complete MVP change set, Azure SSH access, current Compose deployment, private ntfy configuration, and Codex Security skills.
- Produces: passing focused suite, browser evidence at desktop/iPhone sizes, resolved security findings, pushed commit, healthy Azure release, verified scheduler/ntfy continuity, and rollback instructions.

- [ ] **Step 1: Run the complete focused DueSoon suite and compile checks**

Run: `python -m pytest tests/duesoon -q`

Run: `python -m compileall -q src/duesoon`

Run: `git diff --check`

Expected: all DueSoon tests PASS, compile exits 0, and diff check emits no errors.

- [ ] **Step 2: Start a local non-live application and verify browser flows**

Use `DUESOON_ENV=test`, a temporary SQLite database, `DUESOON_DRY_RUN=true`, `DUESOON_SCHEDULER_ENABLED=false`, and `DUESOON_NTFY_ENABLED=false`. Verify with a real browser at 1440×900 and 390×844:

- login success and generic failure;
- desktop sidebar and mobile bottom navigation;
- Home populated, empty, loading, stale, and error states;
- Assistant four supported prompts and unsupported prompt behavior;
- Calendar month/week/agenda, course colors, Today/previous/next, and detail drawer;
- Notifications, Review, Settings, Email, Notes, Memory, and Documents states;
- logout and back-button denial; and
- no console error, horizontal overflow, secret in DOM/storage, or service worker.

- [ ] **Step 3: Run Codex Security diff scan on all MVP commits**

Invoke `codex-security:security-diff-scan` against the branch range beginning at commit `2a7ebe9` and ending at the current MVP HEAD. Scope review to authentication, authorization, CSRF, sessions, rate limiting, frontend injection, Caddy routing, ntfy isolation, secrets, container/runtime changes, and reminder invariants. Record each finding with severity, evidence, and disposition.

- [ ] **Step 4: Run Codex Security active-runtime scan**

Invoke `codex-security:security-scan` on `src/duesoon`, `Dockerfile`, `requirements.txt`, `deploy/azure`, `.env.example`, and the focused tests. Explicitly test:

- session fixation, token leakage, cookie flags, logout/revocation, expiry, and password timing;
- login CSRF, state-changing CSRF, origin validation, and throttle bypass;
- IDOR/authorization on every dashboard API;
- reflected/stored XSS from Canvas titles, URLs, reminder bodies, and assistant questions;
- path traversal/static-file exposure, open redirects, cache leakage, and CSP gaps;
- API-token/browser-session crossover;
- ntfy topic hijacking or routing regression;
- secret/hash exposure in logs, errors, DOM, examples, process arguments, and Git;
- SQL injection, unsafe query bounds, and denial-of-service inputs;
- container user/capabilities, public ports, persistent-volume access, and dependency changes; and
- unchanged immediate submission recheck, checkpoint deduplication, dry-run, and exactly-one-scheduler behavior.

- [ ] **Step 5: Fix confirmed findings and rerun their proofs**

For each confirmed finding, first add a focused regression test that fails, apply the smallest fix, rerun that test, rerun the complete focused DueSoon suite, and commit:

```bash
git add src/duesoon deploy/azure tests/duesoon docs/operations/dashboard-mvp-release.md
git commit -m "fix: remediate dashboard security finding"
```

No confirmed High/Critical finding may be accepted. Any lower-severity finding not fixed requires the owner’s explicit written acceptance in the release document.

- [ ] **Step 6: Write the release and rollback record**

Document exact tested commit, test totals, security scan scopes/results, configured hostname, database backup path, Compose services/images, scheduler worker count, ntfy verification result, browser viewport results, known accepted findings, and rollback commands. The rollback target is the previously deployed commit `2b8173f`; database backup must be taken before starting the new image.

- [ ] **Step 7: Push the verified branch and deploy on Azure**

```bash
git status --short
git push origin main
```

On Azure: fetch the pushed commit, back up `/mnt/duesoon/app/duesoon.db`, run `deploy/azure/configure-owner-login.sh` for the current installation, build the DueSoon image, validate Compose, and run `docker compose up -d --build` using `/etc/duesoon/compose.env`. Do not recreate or delete the ntfy volumes.

- [ ] **Step 8: Verify production and notification continuity**

Run `deploy/azure/verify-runtime.sh`, then verify:

- Caddy, DueSoon, and ntfy are healthy with zero restart loops;
- `/health/ready` and authenticated briefing are 200;
- live Canvas sync advances its latest successful run;
- exactly one scheduler is active at the configured 300-second interval;
- existing reminder history remains intact;
- a submitted fixture/test assignment remains suppressed after immediate Canvas recheck;
- no duplicate reminder is created across a restart; and
- one owner-approved controlled ntfy notification reaches the existing iPhone topic exactly once.

- [ ] **Step 9: Commit the release evidence and leave production green**

```bash
git add docs/operations/dashboard-mvp-release.md
git commit -m "docs: record dashboard MVP release verification"
git push origin main
```

Re-run production health after the documentation-only push. Stop only with a clean working tree, pushed main branch, healthy services, passing focused tests, completed security gate, recorded rollback, and live reminders unchanged.

---

## Deferred Plans After MVP

Create these only after Task 12 is green:

1. `duesoon-model-assistant.md` — OpenAI-compatible primary/fallback routing, evidence-linked answers, model settings, timeouts, and token/cost caps.
2. `duesoon-learning-review.md` — correction questions, durable proposals, approve/edit/reject/undo, scopes, audit, and canonical-change safeguards.
3. `duesoon-gmail-evidence.md` — read-only Gmail OAuth, mailbox reader, minimal cache, attachment evidence, and prompt-injection isolation.
4. `duesoon-google-calendar-retained-tools.md` — read-only Google Calendar overlay, local events, then DueSoon-specific Notes, Memory, and Documents.
5. `duesoon-app-delivery.md` — PWA/native evaluation only after the stable web release.
