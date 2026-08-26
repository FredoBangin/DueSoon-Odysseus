# Legacy Contraction Inventory

**Status:** Runtime isolated; physical contraction in staged follow-up batches.
**Active runtime:** `src/duesoon` only.

## Active DueSoon Foundation

- `src/duesoon/api/app.py`
- `src/duesoon/config/settings.py`
- `src/duesoon/persistence/database.py`
- `tests/duesoon/`
- `Dockerfile`
- `docker-compose.yml`

## Keep and Adapt Before Deletion

| Academic capability | Legacy reference paths | DueSoon destination | Deletion gate |
| --- | --- | --- | --- |
| Assignment/evidence notes | `routes/note_routes.py`, note models in `core/database.py` | `src/duesoon/annotations/` | Typed annotations persist and API tests pass |
| Manual academic obligations | `routes/task_routes.py`, `src/task_scheduler.py` | `src/duesoon/obligations/` | Generic agent actions are absent; manual obligations and scheduler tests pass |
| Academic calendar | `routes/calendar_routes.py`, `src/caldav_sync.py`, `src/caldav_writeback.py` | `src/duesoon/calendar/` | Exams, meetings, deadlines, timezone behavior, and optional ICS/CalDAV tests pass |
| Professor identities | `routes/contacts_routes.py` and CardDAV helpers | `src/duesoon/identity/` | Course-scoped professor matching and optional CardDAV import tests pass |
| Typed learning state | `routes/memory_routes.py`, `src/memory.py`, `src/memory_provider.py` | `src/duesoon/learning/` | Aliases, matching feedback, source reliability, and preference schema tests pass |
| Course documents | `routes/document_routes.py`, `src/document_processor.py`, `src/upload_handler.py` | `src/duesoon/evidence/documents/` | Safe file limits, parsing, provenance, and prompt-injection fixture tests pass |
| Professor email evidence | `routes/email_routes.py`, `src/email_thread_parser.py` | `src/duesoon/evidence/email/` | Read-only ingestion, identity association, provenance, and no-send tests pass |
| Bounded AI extraction | `src/llm_core.py`, structured-output helpers | `src/duesoon/intelligence/` | Schema validation, timeout, malformed output, and deterministic fallback tests pass |
| Optional retrieval | `src/chroma_client.py`, RAG modules | `src/duesoon/retrieval/` | Retrieval has a measured benefit and cannot become authoritative truth |
| Shared persistence lessons | `core/database.py` | `src/duesoon/persistence/` plus migrations | Required entities are migrated and backup/restore proof passes |

## Remove After Runtime Isolation Proof

These features are not DueSoon foundations and need no product replacement:

- Generic chat, assistant personas, sessions, model browsing, presets, and comparison.
- Shell execution, arbitrary tools, MCP, skills marketplace, and background shell jobs.
- Cookbook, local/remote model serving, GPU overlays, SSH, host Docker access, Codex, Copilot, and companion integrations.
- Deep research, generic search, SearXNG, YouTube, and visual reports.
- Image generation, gallery/editor, RealESRGAN, fonts/emoji customization, TTS, STT, and voice.
- Outbound email compose/reply, generic webhooks, and unrelated personal workspace UI.
- Old launchers, desktop packaging, OS services, Node UI tooling, and obsolete documentation/media.

## Contraction Order

1. Confirm `src.duesoon.api.app:app` is the only container entry point.
2. Remove generic agent/tool routes, implementation modules, tests, and static assets.
3. Remove model-serving, media, search, companion, packaging, and platform tooling.
4. Port retained academic primitives one domain at a time.
5. Delete each legacy reference group only after its destination gate passes.
6. Remove root `app.py`, old `routes/`, remaining legacy `src` modules, `core`, and old tests when all retained ports are complete.

Every contraction commit must pass `python -m pytest tests/duesoon -q`, compilation, Compose validation, and a route-absence check. Existing student data must never be deleted as part of source contraction.
