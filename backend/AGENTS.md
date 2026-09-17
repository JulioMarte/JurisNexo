# JurisNexo backend — agent operating map

These instructions add backend-specific execution rules to the repository-wide `AGENTS.md`. They do not replace the normative architecture documents.

## Read before changing persisted legal data

For schema, migration, corpus persistence, bootstrap, or database-contract work, read the relevant repository-wide instructions plus:

- `docs/02-legal-corpus-and-data-model.md`;
- `docs/22-architecture-fitness-functions.md`;
- `docs/27-database-bootstrap-and-multi-court-registry.md`;
- `docs/34-adversarial-legal-reality-v3.md`;
- `docs/testing/current-guarantees.toml`.

Treat the Alembic history as implementation history, not as proof that every historical modeling choice remains canonical. Verify the schema at migration head.

## Legal vocabulary gate — mandatory

Before adding a persisted categorical column, enum, or `CHECK ... IN (...)`, classify the category.

```text
LAW-OWNED
    A legal system, jurisdiction, court, instrument, procedure, role,
    treatment, legal event, legal effect, identifier or similar domain fact
    can introduce or classify the category differently.

SYSTEM-OWNED
    JurisNexo itself defines the workflow/provenance/state-machine value or
    the value is a structural discriminator required by the physical model.
```

For **LAW-OWNED** categories:

- do not freeze the legal vocabulary in DDL;
- use an extensible concept registry with referential integrity;
- adding a newly encountered category must be possible through data rather than a schema migration;
- keep source-native wording separately when provenance requires it;
- do not add a second writable mirror solely for compatibility.

For **SYSTEM-OWNED** categories, a closed `CHECK` may be appropriate when it protects an actual workflow or structural invariant.

When uncertain, inspect `docs/34-adversarial-legal-reality-v3.md` and the final-schema contracts before inventing a new pattern.

## Canonical physical-schema discipline

Do not restore removed compatibility surfaces merely to make an old caller or test pass. In particular, do not reintroduce aliases/mirrors such as `corpus.cases`, scalar matter/procedure/controversy shortcuts, judicial semantic text mirrors, or synchronization triggers that duplicate canonical legal truth.

Update callers and tests to the canonical representation instead.

Unknown legal classification must remain unknown when evidence is insufficient. Do not manufacture certainty through database defaults; `judicial_decisions.act_type_concept_id = NULL` is the intentional representation of an adjudicative act form not yet classified.

## Migration proof

For database-model changes, the minimum completion evidence is:

1. migrations apply from a fresh ephemeral PostgreSQL database;
2. bootstrap succeeds on that database;
3. relevant invariant/integration tests execute against the migration head;
4. `test_legal_reality_v3_schema_contract.py` remains green for canonical physical-shape changes;
5. `test_closed_legal_vocabulary_inventory.py` remains green for legal vocabulary changes;
6. backend quality and the exact-head CI aggregate are green.

A historical migration applying successfully is not enough. The final PostgreSQL schema is the object being protected.

## Test repair discipline

When a schema constraint intentionally changes implementation while preserving or strengthening semantics, update tests to assert the semantic contract rather than the old mechanism. For example, after an open legal vocabulary moves from a closed `CHECK` to a concept FK, an unregistered code should be rejected as a foreign-key violation while a newly registered concept should be accepted without DDL.

Do not weaken unrelated structural, temporal, provenance, same-scope, or evidence invariants while adapting such tests.
