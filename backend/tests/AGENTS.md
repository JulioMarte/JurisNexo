# JurisNexo backend test agent rules

Applies to `backend/tests/**` in addition to repository-wide `AGENTS.md`.

Before adding, deleting, moving, or weakening durable proof, read:

- `docs/testing/README.md`
- `docs/testing/repository-governance-contract.md`
- `docs/testing/evidence-authoring-guide.md`
- `docs/testing/current-guarantees.toml`

## Rigidity versus flexibility

Classify every structural assertion as one of:

```text
HARD        legal/security/provenance invariant or semantic boundary; fail closed
CONTROLLED  accepted architecture/product/repository shape; deliberate evolution only
FLEXIBLE    private implementation shape; do not freeze gratuitously
HISTORICAL  prior benchmark/release/design provenance; evaluate in historical context
```

Do not interpret “tests may evolve” as permission to relax `HARD` boundaries such as source provenance, tenant/security isolation, canonical-write authority, mandatory ingestion audit gates, benchmark independence, or agent/database authority separation.

Do not turn `FLEXIBLE` details such as exact filenames, test counts, private helper names, or internal splits into permanent architecture contracts.

## Evidence integrity

A green test is evidence only when a plausible defect in the claimed behavior would make it fail.

Before authoring durable proof, identify:

```text
protected guarantee / risk
plausible defect
real execution boundary
valid preconditions / dummy world
independent oracle or gold
authoritative state and negative side effects
canonical CI / benchmark lane
```

Do not write tests whose setup manufactures the expected result, whose expected value is computed by the production helper under test, or whose assertions merely mirror incidental implementation shape.

For important bug fixes, use a mutation mindset: name the regression that would reintroduce the defect and ensure the proof would turn red.

## Test ownership

Current physical locations answer ownership/execution boundary:

```text
backend/tests/unit/          isolated logic
backend/tests/integration/   multi-component/application/database behavior
backend/tests/architecture/  dependency, repository, CI and instruction-governance fitness
```

Create `db/`, `e2e/`, shared `fixtures/`, or other durable trees only when real evidence ownership requires them. Do not create ceremonial structure.

Markers answer what evidence a test provides. Use existing declared pytest markers and add new ones only when they materially improve selection or proof meaning.

## PostgreSQL and data evidence

- Use real PostgreSQL when constraints, transactions, locks, isolation, migrations, durable state, or database authority are part of the claim.
- Do not claim database correctness from SQLite, an in-memory repository, mocked SQLAlchemy sessions, or fake locks.
- Build the minimum complete valid legal/product world required by the scenario; avoid magical IDs and impossible partial rows.
- Direct SQL may create valid prerequisites, inspect authoritative state, or directly prove a DB backstop. It must not pre-create the application result under test or disable the enforcement being proved.
- When runtime authorization/tenant behavior is part of the claim, execute the operation through the real supported application/runtime boundary.

## Legal-source and provenance evidence

For source-sensitive tests, preserve the distinction between:

```text
primary artifact/version/checksum
observed page/passage/content evidence
model interpretation
canonical persisted conclusion
```

Model-generated text is never an independent oracle for primary-source truth.

When testing historical bulletins, cases, statutes, or other legal corpora, provenance should remain sufficient to explain exactly which source material supported the assertion.

## Agent/ingestion evidence

Mandatory ingestion gates must be tested as real state/authority transitions:

```text
Structure -> Structure Audit -> Extraction -> Extraction Audit -> Canonical Commit
```

Do not seed post-audit state and then claim to have proven the audit gate.

Provider/model doubles are acceptable only at the external boundary excluded from scope. The application state machine, provenance checks, evidence model, audit transitions, and canonical-write rules must remain real when they are the claim.

## Benchmark evidence

Runtime success is not semantic success.

Keep distinct:

```text
runtime/provider status
navigation/mechanical status
semantic/evidence status
overall benchmark/product status
```

Do not leak gold answers into prompts/tools. Do not weaken scorers solely to make a candidate pass. If the benchmark contract itself is wrong or ambiguous, change/version it explicitly and preserve the reason.

## Correctness-sensitive evidence

- Do not make a race or state-transition proof pass by mocking the mechanism under test.
- Use independent actors/transactions and deterministic synchronization for concurrency.
- Assert winner, loser, final authoritative state, and important absence of partial/duplicate effects.
- Do not assert only HTTP status for durable safety/provenance claims.
- Prefer semantic outcomes over incidental ORM call sequences or broad snapshots.

## Architecture/repository proofs

Architecture tests should strongly enforce `HARD` boundaries, detect `CONTROLLED` drift with actionable messages, and avoid freezing `FLEXIBLE` shape.

Instruction-governance tests should ensure editor/model adapters route back to canonical `AGENTS.md` and `docs/`, rather than becoming independent architecture manuals.

CI-governance tests should verify that architecture fitness functions remain explicitly blocking in the canonical quality lane. They must not pretend to prove GitHub rulesets or branch protection that live outside the repository.

Removing or weakening a safety/architecture/provenance/security/benchmark proof requires an explicit `KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL` disposition tied to the protected guarantee.

Never weaken a test solely because the implementation currently fails it.
