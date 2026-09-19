# JurisNexo — Legal Reality V4 Implementation Checklist

This checklist turns the V4 model into an executable rollout gate. It complements `35-legal-reality-v4.md` and `36-postgresql-vps-operating-contract.md`.

## Implemented in the V4 migration chain

- [x] Shared concept substrate for new cross-domain/cross-jurisdiction legal vocabularies.
- [x] Jurisdiction-aware concept identity and explicit concept edges/aliases.
- [x] First-class `legal_issues` with typed relations and evidence.
- [x] First-class `factual_propositions` separating allegation/finding/etc. from legal propositions.
- [x] Separate extraction confidence from semantic confidence for new interpretive objects.
- [x] Remove `issue`, `material_fact` and `procedural_fact` from new `legal_propositions` writes.
- [x] Replace V3 `disposition_targets` with typed action arguments.
- [x] Add typed literal disposition values: text, number, money, date, duration and percentage.
- [x] Preserve V3 target rows losslessly as `object` arguments before target-table removal.
- [x] Preserve same-proceeding/same-decision disposition context checks.
- [x] Add baseline disposition effect/argument grammar without building a general rules engine.
- [x] Add evidence-bearing entity identity assertions.
- [x] Add bitemporal entity identity resolutions without destructive merge.
- [x] Require persisted evidence for verified V4 issue/fact/entity-identity assertions.
- [x] Add concept hierarchy cycle protection.
- [x] Update V3 tests that protected superseded target mechanics to protect V4 semantics instead.
- [x] Add a dedicated `tests/legal_model/` PostgreSQL suite.
- [x] Update the normative guarantee inventory.
- [x] Update backend agent instructions and documentation precedence.
- [x] Document private PostgreSQL/VPS migration, backup and restore expectations.

## Required before merging V4

- [ ] Fresh PostgreSQL database migrates from revision 0001 to HEAD.
- [ ] Full backend PostgreSQL test suite passes.
- [ ] Ruff passes for source, tests and migrations.
- [ ] Pyright passes.
- [ ] Architecture fitness functions pass.
- [ ] Docker runtime smoke test passes.
- [ ] Exact-head CI aggregate passes.

## Required before applying V4 to a populated private VPS database

- [ ] Create and verify a backup of the real database.
- [ ] Restore that backup into isolated staging.
- [ ] Record the current Alembic revision and PostgreSQL major version.
- [ ] Run the legacy proposition audit:

```sql
SELECT proposition_type, count(*)
FROM corpus.legal_propositions
WHERE proposition_type IN ('issue', 'material_fact', 'procedural_fact')
GROUP BY proposition_type;
```

- [ ] If rows exist, create a reviewed evidence-preserving transformation migration. Do not bypass the `0046` guard.
- [ ] Apply all V4 migrations to restored staging.
- [ ] Run the complete legal-model/integration suite against restored staging.
- [ ] Compare critical source/artifact/legal-object counts before and after.
- [ ] Sample provenance chains from source artifact/page to issue/fact/proposition/disposition.
- [ ] Verify application queries/callers no longer depend on `disposition_targets` or effect `target_type`.
- [ ] Only then schedule the production migration.

## Required before mass canonical ingestion

- [ ] Golden corpus includes ordinary, appellate, cassation/remand, consolidation, partial vote, complex disposition and historical OCR/source-conflict cases.
- [ ] No known dual writable truth remains in the canonical schema.
- [ ] No new law-owned category is frozen in a closed DDL enum without explicit architectural justification.
- [ ] Verified interpretive identities cannot be created without evidence.
- [ ] Source observations can conflict without destructive overwrite.
- [ ] Bitemporal validity/knowledge queries remain covered by tests.
- [ ] Entity resolution preserves observed identities after canonical resolution.
- [ ] Restore exercise has succeeded on the private PostgreSQL operating path.

## Intentionally deferred

These are not blockers for V4 and should not be smuggled into the migration under the label of completeness:

- migrating every mature specialized `*_concepts` registry into the shared concept substrate;
- RDF/OWL/Neo4j conversion;
- a universal `nodes/edges` model;
- a full legal theorem prover;
- a general disposition-rule DSL;
- invented RPO/RTO numbers without an accepted operations requirement;
- destructive squashing/baselining of the Alembic history before the model and real deployment are stable.
