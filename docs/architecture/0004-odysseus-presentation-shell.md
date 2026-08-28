# ADR 0004: Reuse the Odysseus Presentation Shell

## Decision

DueSoon directly reuses the inherited Odysseus navigation hierarchy, stylesheet, theme controls, submenus, and animated backgrounds. DueSoon view modules render academic data inside that shell.

The legacy Odysseus application runtime, service worker, shell execution, unrestricted tools, and backend routes remain inert. All live data access goes through authenticated DueSoon APIs.

Internal connector freshness and service health belong in relevant settings or diagnostic views, not persistent decorative badges in navigation.

## Reason

The inherited presentation is the approved product baseline. Reusing it preserves a coherent interface while the DueSoon backend replaces legacy capabilities incrementally and safely.

## Rollback

The presentation bridge is isolated to the DueSoon static entry point and shell module. It can be reverted without changing the academic database, scheduler, evidence model, or notification engine.
