# Automatic Canvas Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send automatic private ntfy reminders for incomplete Canvas assignments at the 24h, 12h, 6h, 1h, and 15m checkpoints.

**Architecture:** One in-process scheduler runs on the single Azure worker. Each cycle performs an idempotent Canvas sync, detects checkpoint crossings from a persisted successful watermark, immediately refreshes the specific Canvas submission before every send, and records a unique reminder event before calling the existing audited ntfy delivery service. Canvas `due_at` is the initial `effective_due_at` until later evidence-fusion phases replace it.

**Tech Stack:** Python 3.14, FastAPI lifespan tasks, SQLAlchemy/SQLite, httpx, pytest, Docker Compose, private ntfy.

**Spec:** `DUESOON_CODEX_CONTEXT.md` sections 3, 9, 11, 12, 15, 16, 17, 22 Phase 2, and 23.

## Global Constraints

- Use `canvas_due_at` only as the Phase 2 initial effective deadline; preserve a boundary for future `effective_due_at` and `operational_due_at`.
- Standard checkpoints are exactly 24h, 12h, 6h, 1h, and 15m.
- Every live reminder performs an immediate assignment-specific Canvas submission recheck.
- `submitted` and `graded` suppress delivery; `not_submitted`, `late`, and `missing` remain eligible.
- Persist the scheduler watermark and database-backed deduplication key.
- Downtime crossing sends at most the most recent eligible checkpoint per assignment.
- SQLite production uses exactly one scheduler worker.
- Keep logs and API responses free of secrets and raw academic content.
- Run only `tests/duesoon`, compile checks, Compose validation, and live redacted verification.

---

### Task 1: Assignment-Specific Canvas Submission Refresh

**Files:**
- Modify: `src/duesoon/canvas/client.py`
- Modify: `src/duesoon/canvas/sync.py`
- Test: `tests/duesoon/test_canvas_client.py`
- Test: `tests/duesoon/test_canvas_sync.py`

**Interfaces:**
- Produces: `CanvasClient.get_submission(course_id: str, assignment_id: str) -> dict[str, Any]`
- Produces: `CanvasSyncService.refresh_submission(assignment_id: int) -> str`

- [ ] **Step 1: Write failing client and persistence tests.** Assert the client requests `/api/v1/courses/42/assignments/99/submissions/self`, and refresh persists the returned state for assignment 99.
- [ ] **Step 2: Run the two focused tests.**

  Run: `python -m pytest tests/duesoon/test_canvas_client.py::test_get_submission_requests_current_user tests/duesoon/test_canvas_sync.py::test_refresh_submission_updates_only_requested_assignment -q`

  Expected: fail because both methods are missing.

- [ ] **Step 3: Implement minimal methods.** `get_submission` uses the existing sanitized `_request`; `refresh_submission` loads the assignment/course, fetches one submission, persists its source record and normalized state transactionally, then returns the normalized status.
- [ ] **Step 4: Re-run the focused tests and require both to pass.**
- [ ] **Step 5: Commit Task 1.**

### Task 2: Checkpoint Decisions, Events, and Delivery

**Files:**
- Create: `src/duesoon/reminders/__init__.py`
- Create: `src/duesoon/reminders/checkpoints.py`
- Create: `src/duesoon/reminders/service.py`
- Modify: `src/duesoon/notifications/service.py`
- Modify: `src/duesoon/persistence/models.py`
- Test: `tests/duesoon/test_reminders.py`

**Interfaces:**
- Produces: `crossed_checkpoint(due_at, previous_evaluated_at, now) -> int | None`
- Produces: `ReminderService.run_once() -> ReminderRunSummary`
- Produces: `NotificationService.send_reminder(...) -> DeliveryResult`

- [ ] **Step 1: Write failing checkpoint tests.** Hand-check 24h, 12h, 6h, 1h, and 15m equality boundaries, first-run nearest checkpoint, downtime catch-up selecting one checkpoint, and no result when overdue or more than 24h away.
- [ ] **Step 2: Run checkpoint tests and confirm missing-module failure.**
- [ ] **Step 3: Implement deterministic checkpoint selection with timezone-aware UTC normalization.**
- [ ] **Step 4: Run checkpoint tests and require pass.**
- [ ] **Step 5: Write failing service tests.** Use real SQLite models and fake Canvas/publisher boundaries to prove: one incomplete assignment sends once; immediate refresh to submitted suppresses; repeated run deduplicates; watermark crossing selects one newest checkpoint; dry-run persists without publishing.
- [ ] **Step 6: Run service tests and confirm behavior failures.**
- [ ] **Step 7: Add `ReminderEvent` and `SchedulerState` tables.** Unique reminder identity is `(assignment_id, deadline_at, checkpoint_minutes)`. Event records status, recheck status/time, delivery ID, and reason.
- [ ] **Step 8: Generalize notification delivery.** Keep `send_test`; add `send_reminder` through one private audited/deduplicated delivery method.
- [ ] **Step 9: Implement `ReminderService.run_once`.** Sync first, select incomplete future assignments, claim unique events, refresh each specific submission, suppress completed work, send eligible reminders, then advance watermark only after a successful cycle.
- [ ] **Step 10: Run service tests and require pass.**
- [ ] **Step 11: Commit Task 2.**

### Task 3: Single-Worker Scheduler Lifecycle

**Files:**
- Create: `src/duesoon/reminders/scheduler.py`
- Modify: `src/duesoon/config/settings.py`
- Modify: `src/duesoon/api/app.py`
- Modify: `.env.example`
- Modify: `deploy/azure/production.env.example`
- Test: `tests/duesoon/test_settings.py`
- Test: `tests/duesoon/test_scheduler.py`

**Interfaces:**
- Produces: `ReminderScheduler.start() -> None`
- Produces: `ReminderScheduler.stop() -> Awaitable[None]`
- Adds: `DUESOON_SCHEDULER_INTERVAL_SECONDS`, default `300`, range `30..3600`.

- [ ] **Step 1: Write failing settings and lifecycle tests.** Assert interval validation, disabled scheduler never runs, enabled scheduler invokes a cycle, and stop completes without another cycle.
- [ ] **Step 2: Run focused tests and confirm failures.**
- [ ] **Step 3: Implement async scheduler loop.** Use `asyncio.to_thread` for synchronous Canvas/SQLite work, bounded stop waiting, privacy-safe exception logging, and no second worker.
- [ ] **Step 4: Wire scheduler construction/start/stop into FastAPI lifespan only when Canvas and scheduler are enabled.**
- [ ] **Step 5: Run focused tests and require pass.**
- [ ] **Step 6: Commit Task 3.**

### Task 4: Verification and Azure Activation

**Files:**
- Modify: `docs/deployment/AZURE.md`
- Modify locally ignored production environment: `D:\\odd\\.tools\\duesoon-production.env`

**Interfaces:**
- Consumes: production Canvas, ntfy, SQLite, and scheduler settings.
- Produces: live single-worker automatic reminders on Azure.

- [ ] **Step 1: Run focused suite.**

  Run: `python -m pytest tests/duesoon -q --basetemp=.pytest-tmp`

  Expected: all tests pass with zero failures.

- [ ] **Step 2: Run compile check.**

  Run: `python -m compileall -q src/duesoon`

  Expected: exit 0.

- [ ] **Step 3: Validate production Compose.**

  Run: `docker compose --env-file deploy/azure/compose.env.example -f deploy/azure/docker-compose.production.yml config`

  Expected: exit 0 with one DueSoon service worker.

- [ ] **Step 4: Review diff for secrets and unintended legacy changes.**
- [ ] **Step 5: Merge verified branch to `main`, push, and deploy exact commit to Azure.**
- [ ] **Step 6: Enable one scheduler and restart only DueSoon.**
- [ ] **Step 7: Verify readiness, Canvas sync, scheduler status, reminder-event counts, deduplication, and ntfy health using redacted output.**
- [ ] **Step 8: Confirm phone receives a controlled school-data message, while real checkpoint delivery remains governed by actual upcoming deadlines.**

## Self-Review

- Spec coverage: initial Canvas-backed effective deadline, exact checkpoints, crossing, catch-up, immediate submission recheck, persistence, deduplication, dry-run, single worker, and ntfy audit are covered. Evidence fusion, adaptive reminders, urgency scoring, and non-Canvas evidence remain later phases and are not silently claimed here.
- Placeholder scan: no TBD/TODO steps.
- Type consistency: Task 1 refresh status feeds Task 2 suppression; Task 2 `run_once` feeds Task 3 scheduler; Task 3 settings feed Task 4 production activation.
