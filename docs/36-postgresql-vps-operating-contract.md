# JurisNexo — Private PostgreSQL VPS Operating Contract

## Status

Normative operational contract for the canonical PostgreSQL deployment. JurisNexo does **not** depend on Supabase for its database system of record.

## Deployment topology

Maintain separate PostgreSQL databases/environments for development, staging and production. Do not simulate environments with three schemas inside one production database.

Recommended logical separation:

```text
jurisnexo_dev
jurisnexo_staging
jurisnexo_prod
```

Production must not be directly writable from developer laptops as a normal workflow.

## Database roles

Use separate least-privilege roles for separate authorities:

```text
jurisnexo_app       application runtime
jurisnexo_migrator  Alembic/schema changes
jurisnexo_readonly  diagnostics/reporting
jurisnexo_backup    backup/restore automation
```

`jurisnexo_app` must not own the database and must not have ordinary `CREATE`, `ALTER`, `DROP` or function-definition authority. Schema migrations run as `jurisnexo_migrator` through the documented migration workflow.

Credentials are injected through secret management/environment configuration and are never committed to the repository.

## Migration workflow

Every production schema change follows:

```text
fresh ephemeral PostgreSQL -> Alembic HEAD -> full database tests
                           -> restored production-like staging copy -> Alembic HEAD
                           -> invariant/adversarial tests
                           -> backup checkpoint
                           -> production migration
                           -> smoke/invariant checks
```

A migration that passes only on an empty database is not production-ready.

Before applying Legal Reality V4 to a populated database, explicitly query for legacy legal proposition categories:

```sql
SELECT proposition_type, count(*)
FROM corpus.legal_propositions
WHERE proposition_type IN ('issue', 'material_fact', 'procedural_fact')
GROUP BY proposition_type;
```

If any rows exist, stop. Transform them into evidence-bearing `legal_issues` or `factual_propositions` in a dedicated reviewed migration. `0046_v4_hardening` intentionally refuses silent conversion.

## Backup contract

At minimum, production requires:

- automated daily logical or physical backups appropriate to database size;
- encrypted backup storage;
- at least one copy outside the VPS/failure domain;
- retention policy documented in infrastructure configuration;
- PostgreSQL WAL archiving / point-in-time recovery when recovery-point requirements justify it;
- monitoring that distinguishes "backup command succeeded" from "backup artifact is usable".

Do not treat an untested backup as a recovery capability.

## Restore proof

A restore exercise is mandatory on a recurring schedule and before high-risk schema transitions.

The restore proof must create an isolated database and verify at least:

1. the database starts and accepts connections;
2. Alembic version matches the expected snapshot/head;
3. critical table counts are plausible;
4. FK/check/index/trigger catalog is present;
5. the repository's PostgreSQL integration and legal-model invariant suites pass against the restored database;
6. representative source -> artifact -> page -> evidence -> canonical legal object provenance chains remain queryable.

Record restore date, backup identifier, PostgreSQL version, elapsed restore time and test result in operational logs. Do not commit secrets or production data to CI artifacts.

## Pre-deployment schema snapshot

Before each production migration, record non-sensitive schema metadata:

- Alembic revision;
- PostgreSQL version;
- table/index/constraint/trigger counts;
- migration commit SHA;
- backup identifier.

This metadata is diagnostic provenance, not a substitute for the backup.

## Recovery posture

Recovery objectives are product/operations decisions and must be set explicitly. Do not invent RPO/RTO numbers in code or documentation without an accepted operational requirement.

When PITR is enabled, periodically prove that a database can be restored to a chosen timestamp and then advanced to the intended target without violating the legal-model invariants.

## Production migration safety

For destructive or canonical-identity migrations:

- take/verify the pre-migration backup;
- run the migration first on a restored copy of the real database;
- inspect rows that require semantic transformation rather than coercing them;
- avoid `CASCADE` on canonical legal objects unless dependencies were deliberately inventoried;
- prefer migrations that fail loudly to migrations that guess legal meaning;
- keep the application stopped/read-only during migration when concurrent writes could violate migration assumptions.

## PostgreSQL version

Development, CI, staging and production should remain on the same supported major PostgreSQL version whenever practical. A major-version upgrade is its own change and must be tested separately from a legal-model migration.

## Definition of operational readiness

The private VPS database is ready for mass canonical ingestion only when:

- fresh install to Alembic HEAD is reproducible;
- production-like upgrade to HEAD is reproducible;
- the current legal-model invariant suite is green;
- backup creation is automated;
- a restore has been demonstrated;
- credentials and database ownership follow least privilege;
- source artifacts and legal provenance survive restore intact;
- the migration procedure has an explicit rollback/recovery path based on restore, not unsupported Alembic downgrades.
