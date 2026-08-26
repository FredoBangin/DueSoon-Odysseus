# DueSoon Odysseus Extraction Design

**Date:** 2026-08-26
**Status:** Approved by the owner's instruction to implement the previously discussed extraction plan.
**Source of truth:** `DUESOON_CODEX_CONTEXT.md`

## Objective

Convert the Odysseus fork into a small, auditable DueSoon service before adding academic-intelligence features. The first release of this extraction must boot only DueSoon-owned code, retain the inherited source temporarily for reference, and remove unrelated services and dependencies from the runtime and container image.

This stage does not implement Canvas ingestion, evidence fusion, urgency scoring, or live notification delivery. It creates the safe boundary those features will use.

## Product Invariants

- `DUESOON_CODEX_CONTEXT.md` remains the foundational product specification and learning base.
- AI may extract and interpret evidence, but deterministic code owns state changes, deadlines, urgency, reminder eligibility, and delivery decisions.
- Notifications use ntfy first. Twilio remains an optional future adapter.
- Production targets one Azure Linux VM, one scheduler, one containerized application, and SQLite on an attached managed disk.
- The old DueSoon repository and the Odysseus baseline commit remain recoverable.
- Student data and secrets never enter source control, logs, fixtures, or generated examples.

## Extraction Boundary

### Keep and adapt

- FastAPI as the service boundary.
- SQLAlchemy and SQLite as the initial persistence layer.
- Document parsing patterns for course documents.
- Read-only email parsing patterns for professor evidence.
- Calendar, CalDAV, and ICS patterns for academic dates and course meetings.
- Contacts and CardDAV patterns for professor identity resolution.
- Notes for assignment annotations and evidence notes.
- Tasks for manual academic obligations, after replacing generic agent execution.
- Memory concepts for typed aliases, matching feedback, source reliability, and reminder preferences.
- Bounded LLM extraction and optional Chroma retrieval, never as authoritative state.
- ntfy as the primary iPhone notification transport.

### Remove from active runtime

- Generic chat agent, personas, arbitrary tools, MCP, shell execution, and background shell jobs.
- Cookbook, model serving, GPU, SSH, Docker-socket, Codex, Claude, and Copilot integrations.
- Deep research, general web search, SearXNG, image generation/editing/gallery, TTS, STT, voice, YouTube, and model comparison.
- Generic webhook marketplace behavior and outbound email composition or automatic replies.
- Unrelated UI, installers, launchers, service definitions, and platform packaging.

### Quarantine until ported

Inherited files are reference material, not active runtime. Useful modules may stay temporarily under their existing paths while DueSoon replacements are built and verified. No new DueSoon module may import the legacy `app.py`, `routes`, or generic agent stack.

## Runtime Architecture

```text
Azure Linux VM
└── Docker Compose
    ├── duesoon
    │   ├── FastAPI API
    │   ├── settings validation
    │   ├── SQLAlchemy engine and migrations
    │   └── exactly one scheduler (later phase)
    ├── persistent managed-disk mount
    │   └── /app/data/duesoon.db
    └── ntfy
        ├── persistent cache/config
        ├── HTTPS reverse-proxy boundary
        ├── authentication and ACLs
        └── upstream-base-url for iPhone APNs delivery
```

The first extraction starts only the DueSoon API and ntfy. Chroma is omitted until evidence retrieval proves useful. SearXNG is removed. The Docker image contains no browser, Node.js, compiler toolchain, GPU/image stack, SSH client, tmux, or Docker CLI.

## Compatibility and Rollback

Forward path:

1. Add a new `src/duesoon` package and focused tests.
2. Point the container command at `src.duesoon.api.app:app`.
3. Prove health, settings, persistence initialization, and container configuration.
4. Remove inactive runtime dependencies and services.
5. Delete legacy source in later contract batches only after each retained concept has a verified DueSoon replacement.

Rollback path:

- Git can restore the pre-extraction commit.
- The Odysseus baseline is recorded in `docs/migration/ODYSSEUS_BASELINE.md`.
- Existing data is not migrated or deleted in this stage.
- A separate database filename (`duesoon.db`) prevents the new runtime from mutating the inherited Odysseus database.

## Initial API Contract

- `GET /health/live`: returns HTTP 200 when the process is running.
- `GET /health/ready`: returns HTTP 200 only when configuration is valid and the database accepts a query.
- `GET /api/v1/system/info`: returns non-secret service metadata and dry-run state.

No endpoint exposes student content in this stage.

## Configuration Contract

Required production choices are explicit:

- `DUESOON_ENV`: `development`, `test`, or `production`.
- `DUESOON_DATABASE_URL`: defaults to `sqlite:///./data/duesoon.db`.
- `DUESOON_DRY_RUN`: defaults to `true`.
- `DUESOON_SCHEDULER_ENABLED`: defaults to `false` until the scheduler exists.
- `DUESOON_SCHEDULER_WORKERS`: must equal `1` when scheduling is enabled with SQLite.
- `DUESOON_API_TOKEN`: required in production before protected feature endpoints are added.
- `DUESOON_NTFY_URL`, `DUESOON_NTFY_TOPIC`, and `DUESOON_NTFY_TOKEN`: validated when live ntfy delivery is enabled in a later phase.

## Verification Boundary

This extraction is complete when focused DueSoon tests pass, Python compilation passes, Compose resolves to only required services, the container uses the DueSoon app, no removed toolchain appears in the Dockerfile or requirements, and git contains no secret values. Full inherited Odysseus tests are intentionally out of scope because their features are no longer active product behavior.
