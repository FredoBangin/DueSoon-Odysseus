# DueSoon Agent Rules

Read `DUESOON_CODEX_CONTEXT.md` completely before making material changes.
It is the foundational product specification and learning base, not optional notes.

- Preserve the Effective Assignment and evidence/provenance model.
- Use `effective_due_at` and `operational_due_at`, not raw Canvas `due_at`, for decisions.
- Keep AI bounded to extraction and interpretation; deterministic code owns exact behavior.
- Never send a reminder without an immediate Canvas submission recheck.
- Preserve checkpoint crossing, deduplication, dry-run behavior, and auditability.
- Private ntfy delivery is the active notification provider; Twilio remains an optional future adapter.
- Never expose or commit secrets or student academic content.
- Preserve the legacy DueSoon repository and its recovery checkpoint.
- Add or update tests with every behavior change.
- Do not remove inherited Odysseus capabilities until their DueSoon replacements are verified.
- Update the foundational context or an architecture decision record when changing a product invariant.
- Production targets one Azure Linux VM, an attached managed disk for SQLite, Docker Compose, and exactly one scheduler.
- Keep legacy Odysseus code inert until each retained academic primitive has a tested DueSoon replacement.
- Odysseus owns the complete visual system and interaction shell: navigation, menus, submenus, settings panels, popovers, dropdowns, modals, dialogs, cards, forms, buttons, spacing, animations, backgrounds, and responsive behavior. Reuse its original markup, classes, components, and behavior; do not create replacement DueSoon UI patterns.
- Keep product effort focused on DueSoon academic intelligence: evidence ingestion, assignment matching, deadline resolution, urgency, submission detection, reminders, learning, explanations, and notification reliability.
- Be candid and evidence-led with the owner: do not rubber-stamp a plan or agree for comfort. If an assumption, diagnosis, or requested direction is wrong or risky, say so plainly, explain why, and recommend the safer correction.
- Use the installed `caveman` skill for all user-facing agent conversation by default to conserve credits. Keep technical accuracy, security warnings, code, commits, tests, architecture documents, and other durable project artifacts in clear normal prose. Caveman mode remains active until the owner explicitly says `stop caveman` or `normal mode`.

## Current Repository Baseline

- This repository is the Odysseus-based DueSoon implementation.
- Local work began from the curated Odysseus `main` branch.
- `origin` is `https://github.com/FredoBangin/DueSoon-Odysseus.git`.
- `upstream` is `https://github.com/odysseus-dev/odysseus.git`.
- Do not merge this repository into the legacy `FredoBangin/DueSoon` Git history.

## Focused Commands

- DueSoon tests: `python -m pytest tests/duesoon -q`
- Compile check: `python -m compileall -q src/duesoon`
- Compose validation: `docker compose config`

Do not run the full inherited Odysseus test suite unless a task explicitly changes quarantined legacy behavior.
