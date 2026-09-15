---
applyTo: "backend/migrations/**/*.py"
---

# Migration and SQL instructions

This is a tool-specific adapter. Canonical authority remains repository `AGENTS.md`, `backend/migrations/AGENTS.md`, and current data/testing contracts under `docs/`.

When changing schema or migration SQL:

- treat PostgreSQL constraints and provenance/scope relationships as authority boundaries, not incidental implementation;
- prefer forward additive migration history unless an explicit CONTROLLED rebaseline is approved;
- never fabricate or silently overwrite legal source truth during data migration;
- do not weaken constraints merely to make an application path pass;
- prove PostgreSQL-specific behavior against real PostgreSQL, including clean migration upgrade;
- identify affected guarantee IDs and add/adapt invariant evidence when schema semantics change.
