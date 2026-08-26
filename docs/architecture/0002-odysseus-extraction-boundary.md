# ADR 0002: Odysseus Extraction Boundary

**Status:** Accepted
**Date:** 2026-08-26

## Decision

Introduce a clean `src/duesoon` runtime that does not import the inherited Odysseus `app.py`, routes, generic agent stack, or static UI. First make the old runtime unreachable, then port retained academic primitives behind tests, then delete legacy code in explicit contract batches.

Retain and adapt Notes, Tasks, Calendar, Contacts, Memory, Documents, read-only Email, CalDAV/CardDAV/ICS, bounded LLM extraction, and optional Chroma retrieval. Remove generic chat/agents, shell/code execution, MCP/tools, model-serving/GPU/SSH/Cookbook infrastructure, deep research/search, image/voice/YouTube/compare features, coding companions, outbound email automation, broad webhooks, and unrelated UI.

## Consequences

- Legacy source may remain temporarily for reference but is not production behavior.
- Each retained concept needs a typed DueSoon replacement and focused proof before its legacy files are deleted.
- New product features are implemented only under `src/duesoon`.
- Migration remains reversible until contraction batches begin.
