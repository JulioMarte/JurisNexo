# JurisNexo — Test Evidence Authoring Guide

Status: **normative test-evidence authoring guidance**.

This guide defines how contributors and coding agents turn a legal-product, architecture, security, database, ingestion, research, or benchmark claim into credible test evidence.

The governing principle is simple:

> A green test is useful only when it was capable of failing for the defect it claims to detect.

## 1. Authoring workflow

Before writing or modifying durable proof:

1. identify the current guarantee, invariant, contract, failure mode, race, benchmark claim, or architecture rule;
2. classify the protected detail as `HARD`, `CONTROLLED`, `FLEXIBLE`, or `HISTORICAL`;
3. name a plausible defect that must make the proof fail;
4. choose the smallest real execution boundary capable of exposing that defect;
5. build valid, business-plausible preconditions without manufacturing the expected result;
6. exercise the real mechanism under test;
7. assert the authoritative outcome plus important rejected/absent side effects;
8. run the narrow proof first and then the canonical CI lane that owns it.

If step 3 cannot be answered, the proposed test is probably freezing implementation shape rather than protecting a meaningful guarantee.

## 2. Evidence classes

Physical location answers who owns/runs a proof. Markers and the guarantee inventory answer what the proof means.

Use these evidence classes where they add semantic value:

- `fitness`: deterministic repository/dependency/governance constraints;
- `invariant`: durable correctness property at its authority boundary;
- `contract`: supported API/type/schema/state-machine semantics;
- `adversarial`: negative proof against a plausible defect or abuse case;
- `integration`: multiple real components/stages working together;
- `security`: authorization, tenant, credential, or trust boundary evidence;
- `benchmark`: semantic/stochastic quality over controlled inputs and independent gold.

Do not add markers merely to decorate tests.

## 3. Independent oracles and falsifiability

Prefer assertions against authoritative or externally meaningful state:

- persisted source artifact identity/checksum and typed provenance;
- canonical database state after application/API execution;
- explicit rejection plus proof that no partial canonical write escaped;
- audit-gate state proving an agent output did not bypass mandatory review;
- winner/loser semantics and final state for concurrency;
- frozen benchmark gold independent from the implementation under test;
- trace/evidence records sufficient to explain what source material supported a result.

Do not compute the expected result with the same production helper that generated the actual result. Do not copy production branching logic into the test and call that an oracle.

For important regressions, use a mutation mindset: identify the smallest realistic code change that would reintroduce the bug and ensure the proof turns red under that mutation.

## 4. Legal-source and provenance evidence

JurisNexo is a legal evidence system. Tests involving legal documents must distinguish primary-source facts from model interpretation.

A provenance-sensitive proof should verify, as applicable:

```text
source artifact identity
source version/checksum
page or passage identity
observed content/evidence
model-derived interpretation
canonical-write/audit state
```

Do not let test fixtures silently replace primary-source identity with model-generated text. When testing extraction or research, the expected legal answer must be traceable to independent source/gold material.

## 5. PostgreSQL evidence must use PostgreSQL

When the guarantee depends on PostgreSQL semantics, use the real PostgreSQL version selected by repository CI. This includes constraints, foreign keys, transaction isolation, locks, concurrent writers, uniqueness, authorization/RLS where applicable, durable job state, and migration behavior.

Do not replace the mechanism under test with SQLite, an in-memory repository, a mocked SQLAlchemy session, or a fake lock and then claim database correctness.

Direct SQL is acceptable for valid setup, authoritative inspection, or direct proof of a database backstop. It must not pre-create the final outcome the application operation is supposed to produce or disable the enforcement being tested.

## 6. Security and tenant evidence

If the claim concerns authorization, tenant isolation, production credential boundaries, or canonical-write authority, execute the operation through the real supported runtime/application boundary wherever that boundary is part of the guarantee.

A privileged setup connection may establish valid prerequisites. It does not prove that the runtime principal is correctly restricted.

Do not treat an LLM guardrail or prompt instruction as evidence for a deterministic authorization invariant.

## 7. Agent and ingestion evidence

For the mandatory ingestion sequence, tests must preserve the distinction between:

```text
Structure
Structure Audit
Extraction
Extraction Audit
Canonical Commit
```

A test that bypasses an audit stage by directly seeding the state expected after that stage cannot prove that the gate works.

Provider/model doubles are allowed at the remote provider boundary when the provider itself is not the claim. The application state machine, evidence model, audit transitions, provenance checks, and canonical-write rules must remain real when those are the guarantees under test.

## 8. Research and benchmark evidence

A successful workflow execution is not semantic proof.

Benchmark evidence should keep separate:

```text
runtime/provider status
navigation/mechanical status
semantic/evidence status
overall benchmark/product status
```

Use controlled inputs and independent gold where appropriate. Do not leak gold answers into prompts, tools, fixtures visible to the agent, or expected-value helpers. Do not weaken a scorer merely because the candidate implementation fails it.

When a benchmark changes, state whether the change is correcting an ambiguous/incorrect contract or making the task easier. The latter requires explicit product/benchmark justification and usually a new version.

## 9. Concurrency and long-running-job evidence

For contested state or durable job transitions:

- use independent transactions/actors when concurrency is the claim;
- coordinate interleavings deterministically rather than relying only on `sleep()`;
- assert winner and loser semantics;
- inspect final durable state;
- verify no duplicate canonical effect, partial write, leaked lease/lock, or impossible transition remains.

## 10. Common false-positive shortcuts

Reject a test design that, without a specific documented reason:

- asserts only HTTP status while ignoring authoritative state;
- mocks the component that owns the invariant being claimed;
- seeds the expected result before executing the operation;
- uses impossible database states merely to make the assertion pass;
- bypasses the runtime role for an authorization claim;
- computes expected output with the implementation under test;
- tests only the happy path for a rejection/safety guarantee;
- depends on execution order or shared mutable state;
- weakens a failing proof solely to make CI green;
- treats model output as independent legal ground truth.

## 11. Test placement

Current durable locations are intentionally small:

```text
backend/tests/unit/          isolated logic with no real external authority boundary
backend/tests/integration/   multi-component/application/database behavior
backend/tests/architecture/  repository, dependency, instruction and governance fitness functions
```

Create additional locations such as `db/`, `e2e/`, or shared `fixtures/` only when real evidence ownership requires them. Do not create ceremonial directory trees.

## 12. Review checklist

Before accepting a durable test, answer:

```text
What guarantee or risk does this prove?
What plausible defect makes it fail?
Is the protected detail HARD/CONTROLLED rather than incidental FLEXIBLE shape?
Is setup valid and independent from the expected result?
Is the real mechanism under test exercised?
Is the oracle independent?
If PostgreSQL semantics matter, is real PostgreSQL used?
If authority matters, is the real supported authority boundary used?
If legal semantics matter, is source/gold independent from model output?
Does the assertion inspect authoritative outcome and important absent side effects?
Which canonical CI/benchmark lane owns this proof?
```

If those questions cannot be answered, the test is not yet credible evidence.

## 13. Validation discipline

Run the narrowest relevant proof while iterating, then the canonical CI lane. Exact-head GitHub CI is merge evidence. Semantic benchmarks are separate evidence and must not be reported as passing unless that benchmark actually ran against the intended commit, model/provider configuration, source version, and gold.
