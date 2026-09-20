# PostgreSQL migration rebaseline

Date: 2026-09-19

## Decision

JurisNexo treats PostgreSQL plus Alembic as the deployment database contract.
The migration baseline must not depend on Supabase-specific migration history, runtime services, deployment APIs, or metadata.

The repository had accumulated 47 active Alembic revisions (0001 through 0047). Those revisions were useful while the legal model was evolving quickly, but replaying every intermediate model is no longer desirable for a new deployment.

## Rebaseline contract

The rebaseline is generated from the resulting PostgreSQL state, not by concatenating migration source files:

1. create an empty PostgreSQL database;
2. apply the complete existing Alembic history;
3. dump the resulting PostgreSQL schema and all rows introduced by migrations;
4. exclude only Alembic's own version table and psql-only client metacommands;
5. remove the superseded revision files from the current tree; Git history remains the audit trail;
6. make one Alembic baseline revision execute that canonical dump;
7. create a second empty PostgreSQL database from the baseline only;
8. compare both normalized dumps byte-for-byte;
9. run bootstrap and the database/legal-model contract suites against the baseline-built database.

A baseline is invalid if any PostgreSQL object or migration-owned row differs.

## What is included

The baseline preserves the final state of schemas, tables, columns, indexes, constraints, foreign keys, sequences, functions, triggers, extensions and static rows introduced by migrations. Historical create/alter/drop churn disappears because the baseline is a snapshot of final state.

Application corpus data is not part of the baseline because the source database used to generate it is clean and contains only migration-owned state.

## Existing deployments

Existing databases already at the pre-baseline Alembic head `0047_treatment_legal_issues` must not replay the baseline. Their schema is already the schema represented by the baseline. Deployment tooling must stamp those databases to the baseline revision as a one-time migration-history transition after verifying that they are exactly at `0047_treatment_legal_issues`.

New databases start directly from the baseline and then apply every later forward migration normally.

## Portability

The active contract is PostgreSQL plus Alembic. Supabase may be used as an optional local utility, but JurisNexo deployment and migration correctness must not depend on Supabase.


## Permanent equivalence proof

The repository keeps a historical equivalence check in
`backend/scripts/verify_migration_baseline_equivalence.sh`, executed by
`.github/workflows/database-baseline-equivalence.yml`.

That check rebuilds one PostgreSQL database from the exact pre-baseline commit
(`998398d275081590a229f90eebb53f9abf1bd80c`) and another from the active
baseline, then compares:

- full schema DDL including PostgreSQL comments;
- migration-owned data after deterministic normalization of generated UUIDs and timestamps;
- Alembic version-table row-level-security hardening.

This is intentionally a historical proof against the current consolidation cut. While the database model is still being completed in this development phase, the baseline may be deliberately regenerated to incorporate additional agreed schema work. Once the baseline is declared complete for the first stable deployment epoch, future changes must move to normal forward Alembic migrations on top of it.
