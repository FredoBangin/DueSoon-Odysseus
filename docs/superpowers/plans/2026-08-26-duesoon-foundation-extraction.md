# DueSoon Foundation Extraction Implementation Plan

> **Execution rule:** Follow this plan in order. Add behavior through failing tests first. Preserve a reversible boundary until new runtime proof passes.

**Goal:** Replace the active Odysseus runtime with a minimal DueSoon FastAPI/SQLite foundation, make ntfy the primary notification design, and remove unrelated infrastructure from the production path.

**Architecture:** New code lives under `src/duesoon`. Legacy Odysseus code remains temporarily inert and unimported. Docker Compose starts one DueSoon API service and one ntfy service. SQLite uses a dedicated `duesoon.db` file on a persistent managed-disk mount.

**Stack:** Python 3.14, FastAPI, Pydantic Settings, SQLAlchemy 2, SQLite, Uvicorn, pytest, Docker Compose, ntfy.

---

## Task 1: Record decisions and migration state

**Files:**

- Modify: `DUESOON_CODEX_CONTEXT.md`
- Modify: `AGENTS.md`
- Modify: `docs/migration/ODYSSEUS_BASELINE.md`
- Create: `docs/architecture/0001-azure-ntfy-runtime.md`
- Create: `docs/architecture/0002-odysseus-extraction-boundary.md`

**Steps:**

1. Replace mandatory Twilio language with ntfy-primary and optional-Twilio language.
2. Add Azure VM, managed-disk SQLite, single-scheduler, and iPhone/APNs ntfy constraints.
3. Record retained/adapted Notes, Tasks, Calendar, Contacts, Memory, Documents, Email, CalDAV/CardDAV/ICS, LLM, and optional Chroma concepts.
4. Correct the local checkout path and baseline verification state.
5. Run `rg -n "Twilio SMS.*required|current provider is Twilio|OneDrive\\Desktop\\odd|remain separate baseline" DUESOON_CODEX_CONTEXT.md AGENTS.md docs/migration/ODYSSEUS_BASELINE.md` and expect no stale invariant text.

## Task 2: Add settings contract test-first

**Files:**

- Create: `tests/duesoon/test_settings.py`
- Create: `src/duesoon/__init__.py`
- Create: `src/duesoon/config/__init__.py`
- Create: `src/duesoon/config/settings.py`

**Steps:**

1. Write tests for safe defaults, environment parsing, secret redaction, and the SQLite single-worker invariant.
2. Run `python -m pytest tests/duesoon/test_settings.py -q` and confirm failure because package does not exist.
3. Implement a cached Pydantic settings object with `DUESOON_` prefix.
4. Run the same test and expect success.

## Task 3: Add database readiness test-first

**Files:**

- Create: `tests/duesoon/test_database.py`
- Create: `src/duesoon/persistence/__init__.py`
- Create: `src/duesoon/persistence/database.py`

**Steps:**

1. Test SQLite foreign-key activation, connection/query readiness, parent-directory creation, and no dependency on `core.database`.
2. Run `python -m pytest tests/duesoon/test_database.py -q` and confirm failure.
3. Implement a SQLAlchemy engine factory and readiness probe without import-time database creation.
4. Run the same test and expect success.

## Task 4: Add minimal FastAPI service test-first

**Files:**

- Create: `tests/duesoon/test_api.py`
- Create: `src/duesoon/api/__init__.py`
- Create: `src/duesoon/api/app.py`

**Steps:**

1. Test liveness, readiness, system metadata, no secret leakage, and absence of inherited routes such as `/shell`, `/chat`, `/gallery`, and `/mcp`.
2. Run `python -m pytest tests/duesoon/test_api.py -q` and confirm failure.
3. Implement an application factory and module-level app. Keep scheduler disabled.
4. Run the same test and expect success.

## Task 5: Replace runtime dependencies and container

**Files:**

- Modify: `requirements.txt`
- Modify: `requirements-optional.txt`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `.dockerignore`
- Modify: `.env.example`
- Delete: `docker-compose.gpu-amd.yml`
- Delete: `docker-compose.gpu-nvidia.yml`
- Delete: `docker/build-realesrgan-wheels.sh`

**Steps:**

1. Add a static contract test in `tests/duesoon/test_runtime_manifest.py` proving SearXNG, Chroma, GPU/image tooling, SSH, Node.js, Docker CLI, MCP, TTS/STT, and generic agent dependencies are absent from active manifests.
2. Run that test and confirm failure against inherited manifests.
3. Reduce requirements to the foundation stack and document future optional groups without installing them.
4. Replace Dockerfile with a non-root, health-checked DueSoon image.
5. Replace Compose with `duesoon` and `ntfy` services, persistent volumes, localhost-safe defaults, and production override hooks.
6. Run `python -m pytest tests/duesoon/test_runtime_manifest.py -q` and expect success.
7. Run `docker compose config` when Docker CLI is available. This check does not require Docker Desktop to be running.

## Task 6: Mark legacy source inert and define contraction inventory

**Files:**

- Create: `legacy/README.md`
- Create: `docs/migration/LEGACY_CONTRACTION_INVENTORY.md`
- Modify: `README.md`

**Steps:**

1. Document that `app.py`, `routes/`, legacy `src` modules, and old static UI are not active runtime.
2. List exact keep/adapt, remove, and quarantine paths.
3. State deletion gates for each retained academic primitive.
4. Replace root README with DueSoon setup, focused verification, dry-run, Azure storage, and ntfy instructions while retaining license and Odysseus attribution.
5. Do not delete the quarantined files in this task; runtime isolation is the reversible migration stage. Physical contraction follows verified ports.

## Task 7: Focused verification and delivery

**Files:**

- Modify as needed based on verification failures only.

**Steps:**

1. Run `python -m pytest tests/duesoon -q`.
2. Run `python -m compileall -q src/duesoon`.
3. Run a FastAPI in-process smoke test for all three endpoints.
4. Run `docker compose config`.
5. Run secret scans using `git diff --check` and targeted `rg` patterns without reading `.env`.
6. Review `git diff --stat`, `git diff`, and `git status --short`.
7. Commit with a normal descriptive message.
8. Push `main` to `origin` after fresh verification remains green.

## Deferred Follow-up Plans

After this foundation passes, create separate test-first plans for:

1. Canvas assignments and submissions ingestion.
2. Inbox, announcements, modules, files, professor email, and course-document evidence.
3. Effective Assignment matching, evidence fusion, deadline resolution, confidence, and conflicts.
4. Urgency scoring, checkpoint crossing, pre-send submission recheck, deduplication, and due-date changes.
5. Live ntfy delivery and adaptive reminder learning.

These are product features, not part of the pre-feature extraction boundary.
