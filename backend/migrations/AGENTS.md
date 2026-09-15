# JurisNexo migration agent rules

Applies to `backend/migrations/**` in addition to repository-wide `AGENTS.md`.

Migrations are executable data-contract history. Treat them as correctness-sensitive code, not as generated boilerplate.

## Default rules

- Prefer additive forward migrations. Do not rewrite an already accepted migration merely because editing it is easier.
- A migration-history rebaseline is a separate CONTROLLED operation and requires an explicit repository decision, coherent docs, clean-database proof, and compatibility analysis.
- Do not fabricate, infer, or overwrite legal source truth during a data migration. Preserve provenance and unresolved/ambiguous states when facts are not authoritative.
- Constraints, foreign keys, uniqueness, scope/tenant relationships, provenance links, and canonical-write backstops are part of the authority model.
- Do not weaken a database constraint solely to make an application path pass.
- Avoid irreversible destructive changes unless the owning contract explicitly requires them and the migration/rollback/data-retention consequences are documented.

## Required evidence

When changing schema or migration behavior:

1. identify affected guarantee IDs in `docs/testing/current-guarantees.toml`;
2. explain the failure mode the schema/backstop prevents;
3. run against real PostgreSQL, including a clean upgrade through the current migration history;
4. add/adapt an invariant or contract test when database behavior is part of the guarantee;
5. verify application code does not silently bypass the new authority boundary.

Direct SQL in migration tests may inspect or establish valid state. It must not disable the mechanism being proven or manufacture an application outcome and then call that application proof.

Never claim migration safety from SQLite, mocks, or static inspection alone when PostgreSQL semantics are material.
