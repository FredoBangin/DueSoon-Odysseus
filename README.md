# DueSoon

DueSoon is an evidence-backed academic intelligence system. This repository began as a curated fork of Odysseus, but the active service is now an isolated DueSoon FastAPI/SQLite foundation under `src/duesoon`.

Read `DUESOON_CODEX_CONTEXT.md` before making material product or architecture changes. It is the foundational specification and learning base, not optional notes.

## Current Stage

Implemented foundation:

- validated dry-run-first configuration;
- minimal FastAPI liveness, readiness, and non-secret system endpoints;
- isolated SQLAlchemy/SQLite connection layer with foreign keys;
- one-worker SQLite invariant;
- lean non-root container;
- Compose topology containing only DueSoon and private ntfy;
- Azure Linux VM and attached-managed-disk deployment decision; and
- focused DueSoon tests.
- read-only Canvas courses, assignments, and current-user submissions;
- opaque Canvas pagination with retry and cross-origin protection;
- idempotent source records and assignment snapshots; and
- course, assignment, detail, and manual Canvas sync APIs.

Effective Assignment resolution, urgency, the scheduler, and automated assignment
notification publishing remain next phases.

The current controlled prototype includes a token-guarded, idempotent
`POST /api/v1/notifications/test` endpoint. It audits dry-run and live ntfy
outcomes but does not yet schedule assignment reminders.

## Local Development

Python 3.12 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn src.duesoon.api.app:app --host 127.0.0.1 --port 7000
```

Safe defaults keep dry-run enabled, the scheduler disabled, ntfy delivery disabled, and the API bound to loopback through Compose.

## Focused Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/duesoon -q
.\.venv\Scripts\python.exe -m compileall -q src/duesoon
docker compose config
```

The full inherited Odysseus suite is not the product gate. Legacy code is inert migration reference material; see `docs/migration/LEGACY_CONTRACTION_INVENTORY.md`.

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Endpoints:

- `GET http://127.0.0.1:7000/health/live`
- `GET http://127.0.0.1:7000/health/ready`
- `GET http://127.0.0.1:7000/api/v1/system/info`
- `POST http://127.0.0.1:7000/api/v1/canvas/sync`
- `GET http://127.0.0.1:7000/api/v1/courses`
- `GET http://127.0.0.1:7000/api/v1/assignments`
- `GET http://127.0.0.1:7000/api/v1/assignments/{id}`

## Canvas Prototype

Add these values to `.env`:

```env
DUESOON_CANVAS_ENABLED=true
DUESOON_CANVAS_BASE_URL=https://school.instructure.com
DUESOON_CANVAS_ACCESS_TOKEN=replace-with-read-only-student-token
DUESOON_API_TOKEN=replace-with-long-random-api-token
```

Trigger a read-only sync:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:7000/api/v1/canvas/sync `
  -Headers @{ "X-API-Token" = $env:DUESOON_API_TOKEN }
```

Canvas data is stored idempotently in SQLite. Raw API payloads remain internal; public assignment responses expose normalized academic fields only.
When `DUESOON_API_TOKEN` is configured, sync and all academic-data endpoints require the `X-API-Token` header.

ntfy starts with default access set to `deny-all`. Create a user/token and grant only that user access to the private DueSoon topic before enabling `DUESOON_NTFY_ENABLED`. Production also requires HTTPS and an iPhone subscription to the self-hosted server/topic.

## Azure Storage

Initial production target is one Azure Linux VM using Docker Compose. Mount an attached Azure managed disk on the host, set `DUESOON_DATA_DIR` to a directory on that disk, and keep exactly one scheduler. Do not store SQLite on Azure Files.

## Security

- Never commit `.env`, tokens, Canvas content, professor messages, course documents, databases, or backups.
- Keep `DUESOON_DRY_RUN=true` until decisions and rendered notifications are reviewed.
- Keep ntfy private with HTTPS, bearer-token authentication, topic ACLs, and persistent auth/cache volumes.
- Never expose inherited shell, agent, MCP, model-serving, or outbound email functionality.

## Provenance and License

This work preserves the repository's existing license and attribution files. See `LICENSE` and `ACKNOWLEDGMENTS.md`. The upstream baseline and fork policy are recorded in `docs/migration/ODYSSEUS_BASELINE.md`.
