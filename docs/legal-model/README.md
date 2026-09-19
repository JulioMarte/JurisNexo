# JurisNexo legal-model index

Use this directory as a short navigation layer, not as a second architecture authority.

Current persisted legal reality is defined by the ordered refinements in the parent `docs/` directory, ending with `35-legal-reality-v4.md`. Operational PostgreSQL expectations are in `36-postgresql-vps-operating-contract.md`, and rollout gates are in `37-legal-model-v4-implementation-checklist.md`.

## Core invariants

1. Source/document evidence is preserved separately from canonical legal interpretation.
2. Controversy, proceeding, claim, procedural event and judicial decision are distinct identities.
3. Legal questions, factual propositions and legal propositions are distinct identities.
4. Allegation does not mean finding; confidence does not mean verification.
5. Dispositive actions have semantic arguments, not one universal target type.
6. Entity identity resolution is evidence-bearing and reversible in knowledge history; observed identities are preserved.
7. Legal validity time and JurisNexo knowledge time remain independently queryable where the claim is temporal.
8. Law-owned vocabularies remain extensible data; physical discriminators/workflow states may use closed checks.
9. Unknown classification remains unknown rather than receiving a fabricated default.
10. Material legal claims must remain traceable to evidence.

Executable evidence lives primarily in `backend/tests/legal_model/` plus the existing PostgreSQL integration/adversarial suites. The normative machine-readable guarantee inventory is `docs/testing/current-guarantees.toml`.
