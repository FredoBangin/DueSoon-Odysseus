# DueSoon Agent Rules

Read `DUESOON_CODEX_CONTEXT.md` completely before making material changes.
It is the foundational product specification and learning base, not optional notes.

- Preserve the Effective Assignment and evidence/provenance model.
- Use `effective_due_at` and `operational_due_at`, not raw Canvas `due_at`, for decisions.
- Keep AI bounded to extraction and interpretation; deterministic code owns exact behavior.
- Never send a reminder without an immediate Canvas submission recheck.
- Preserve checkpoint crossing, deduplication, dry-run behavior, and auditability.
- Twilio SMS with API-key authentication is the active notification provider.
- Never expose or commit secrets or student academic content.
- Preserve the legacy DueSoon repository and its recovery checkpoint.
- Add or update tests with every behavior change.
- Do not remove inherited Odysseus capabilities until their DueSoon replacements are verified.
- Update the foundational context or an architecture decision record when changing a product invariant.

## Current Repository Baseline

- This repository is the Odysseus-based DueSoon implementation.
- Local work began from the curated Odysseus `main` branch.
- `origin` is `https://github.com/FredoBangin/DueSoon-Odysseus.git`.
- `upstream` is `https://github.com/odysseus-dev/odysseus.git`.
- Do not merge this repository into the legacy `FredoBangin/DueSoon` Git history.
