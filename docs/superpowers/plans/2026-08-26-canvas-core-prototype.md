# Canvas Core Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Canvas-to-SQLite-to-FastAPI vertical slice for courses, assignments, and current-user submissions.

**Architecture:** A typed Canvas client follows opaque same-origin pagination links and returns raw objects. A sync service normalizes each object, stores immutable source records/snapshots, and upserts current course, assignment, and submission state in one transaction per course. FastAPI exposes manual sync and read-only academic data endpoints.

**Tech Stack:** Python 3.12+, FastAPI 0.141.1, HTTPX 0.28.1, Pydantic Settings 2.15.0, SQLAlchemy 2.0.52, SQLite, pytest.

**Spec:** `DUESOON_CODEX_CONTEXT.md` sections 5.1, 5.2, 5.9, 16, 17, 22 Phase 1, and 23.

## Global Constraints

- Canvas access is read-only and disabled by default.
- Access token never appears in logs, API responses, errors, or persisted payloads.
- Pagination follows Canvas `Link` URLs as opaque values but rejects cross-origin links.
- Sync is idempotent; repeated identical input creates no duplicate source records or snapshots.
- Submission statuses normalize to `not_submitted`, `submitted`, `graded`, `missing`, `late`, or `unknown`.
- API startup creates prototype tables without importing legacy Odysseus persistence.
- Dry-run controls notifications, not read-only Canvas ingestion.

---

### Task 1: Canvas Configuration

**Files:**
- Modify: `src/duesoon/config/settings.py`
- Modify: `.env.example`
- Test: `tests/duesoon/test_settings.py`

**Interfaces:**
- Produces: `canvas_enabled`, `canvas_base_url`, `canvas_access_token`, `canvas_timeout_seconds`, `canvas_max_attempts` on `DueSoonSettings`.

- [ ] Add failing tests for disabled defaults, required URL/token, URL normalization, secret redaction, and production HTTPS.
- [ ] Run `python -m pytest tests/duesoon/test_settings.py -q`; confirm failure from missing fields.
- [ ] Add validated fields and invariants.
- [ ] Re-run test; expect pass.

### Task 2: Academic Persistence Schema

**Files:**
- Create: `src/duesoon/persistence/models.py`
- Modify: `src/duesoon/persistence/database.py`
- Modify: `src/duesoon/persistence/__init__.py`
- Test: `tests/duesoon/test_models.py`

**Interfaces:**
- Produces: `Base`, `Course`, `SourceRecord`, `Assignment`, `AssignmentSnapshot`, `Submission`, `SyncRun`, `create_schema(engine)`, `session_factory(engine)`.

- [ ] Add failing tests for table creation, unique Canvas identities, foreign keys, and source/snapshot deduplication.
- [ ] Run model tests; confirm missing module failure.
- [ ] Implement models and explicit schema bootstrap.
- [ ] Re-run model tests; expect pass.

### Task 3: Canvas Client and Normalization

**Files:**
- Create: `src/duesoon/canvas/__init__.py`
- Create: `src/duesoon/canvas/client.py`
- Create: `src/duesoon/canvas/normalize.py`
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`
- Test: `tests/duesoon/test_canvas_client.py`
- Test: `tests/duesoon/test_canvas_normalize.py`

**Interfaces:**
- Produces: `CanvasClient.list_courses()`, `CanvasClient.list_assignments(course_id)`, `normalize_course(raw)`, `normalize_assignment(raw)`, `normalize_submission(raw)`.

- [ ] Add failing HTTPX mock-transport tests for bearer auth, `per_page=100`, opaque pagination, cross-origin rejection, 429 retry, and sanitized errors.
- [ ] Add failing normalization tests covering null dates and all six submission states.
- [ ] Run both files; confirm missing module failures.
- [ ] Implement minimal client and pure normalization functions.
- [ ] Re-run both files; expect pass.

### Task 4: Idempotent Canvas Sync

**Files:**
- Create: `src/duesoon/canvas/sync.py`
- Test: `tests/duesoon/test_canvas_sync.py`

**Interfaces:**
- Consumes: Canvas client, normalizers, persistence models.
- Produces: `CanvasSyncService.sync() -> SyncSummary`.

- [ ] Add failing test using an in-memory fake client; assert persisted courses, assignments, submissions, source records, snapshots, and summary counts.
- [ ] Add failing repeated-sync test; assert no duplicate source records/snapshots.
- [ ] Implement transactional upsert and SHA-256 canonical JSON content hashes.
- [ ] Re-run sync tests; expect pass.

### Task 5: Canvas and Assignment API

**Files:**
- Modify: `src/duesoon/api/app.py`
- Test: `tests/duesoon/test_canvas_api.py`

**Interfaces:**
- Produces: `POST /api/v1/canvas/sync`, `GET /api/v1/courses`, `GET /api/v1/assignments`, `GET /api/v1/assignments/{id}`.

- [ ] Add failing API tests for disabled sync, injected successful sync, course/assignment lists, detail with normalized submission, and 404.
- [ ] Run API tests; confirm route failures.
- [ ] Add dependency-injected sync service and session-backed response queries.
- [ ] Re-run API tests; expect pass.

### Task 6: Verification and Delivery

**Files:**
- Modify: `README.md`
- Modify: `docs/migration/LEGACY_CONTRACTION_INVENTORY.md`

- [ ] Document Canvas environment variables and manual sync flow.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall -q src/duesoon`.
- [ ] Run API smoke and `docker compose config --quiet`.
- [ ] Run `git diff --check` and staged secret-pattern scan.
- [ ] Commit and push `main` only after every check passes.
