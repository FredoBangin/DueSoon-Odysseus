# Odysseus Baseline Record

## Source

- Upstream repository: `https://github.com/odysseus-dev/odysseus.git`
- Curated source branch: `main`
- Baseline commit: `451900fc151554f4c8654d1e4d3dadc1d029b047`
- Fork repository: `https://github.com/FredoBangin/DueSoon-Odysseus.git`
- Local checkout: `D:\odd`

## Remote Policy

- `origin` points to the user-owned DueSoon-Odysseus fork.
- `upstream` points to the official Odysseus repository.
- DueSoon changes must not be made in the preserved legacy DueSoon repository.
- Upstream updates should be reviewed and intentionally incorporated; do not blindly merge them into DueSoon.

## Baseline Status

The source checkout, remote configuration, dependency installation, database initialization,
application startup, and health response were verified before extraction. The full inherited
Odysseus suite was intentionally not run because the owner requested focused verification and
the unrelated features are being removed from the active product. DueSoon-specific tests and
runtime checks are the acceptance gate from this point forward.
