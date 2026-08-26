# Inert Odysseus Reference Source

The active application is `src.duesoon.api.app:app`. The root `app.py`, `routes/`, inherited modules under `src/`, `core/`, `static/`, and old platform tooling are not loaded by the DueSoon container or covered by the default test command.

They remain temporarily in Git as migration reference material. Do not add new DueSoon behavior to them. Port useful academic concepts into `src/duesoon` behind focused tests, then delete the corresponding legacy files in a reviewed contraction commit.

See `docs/migration/LEGACY_CONTRACTION_INVENTORY.md` for ownership and deletion gates.
