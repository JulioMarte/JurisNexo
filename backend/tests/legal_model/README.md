# Legal-model PostgreSQL tests

This directory contains executable legal-domain invariants against the real PostgreSQL schema at Alembic HEAD.

These are not unit tests of SQL strings and they are not a replacement for semantic ingestion benchmarks. They create adversarial legal states inside rollback-only transactions and prove what PostgreSQL accepts or rejects.

V4 focuses on the gaps identified by the adversarial domain review:

- jurisdiction-aware shared concepts;
- legal issue identity;
- allegation/finding separation;
- typed dispositive action arguments;
- same-proceeding/same-decision dispositive context;
- auditable entity resolution;
- evidence gates for verified interpretive objects;
- absence of superseded V3 persistence surfaces.

When adding a new legal-model test, prefer a real legal-world counterexample over testing incidental column order or implementation details. A schema refactor may replace the mechanism only when the same or stronger invariant remains demonstrably enforced.
