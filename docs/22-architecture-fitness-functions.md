# JurisNexo — Architecture Fitness Functions

> **Status:** normative for executable architecture constraints.
>
> This document complements the current architecture, security, evidence, agent-runtime, Corpus API, job-state, benchmark, and implementation-governance documents. Tests under `backend/tests/architecture/` enforce structural rules; they do not replace semantic, PostgreSQL, security, or benchmark evidence.

## 1. Purpose

JurisNexo treats architecture as an executable constraint, not only prose and diagrams.

A change may compile, pass unit tests, and still be architecturally invalid if it crosses a trust or ownership boundary that the product depends on.

The fitness-function system has three connected layers:

```text
normative semantic guarantees
        ↓
architecture fitness functions
        ↓
required CI gate
```

The normative guarantee inventory is:

`docs/testing/current-guarantees.toml`

It records durable guarantees, not exact test filenames. Tests may evolve without turning incidental repository shape into permanent architecture.

## 2. Guarantee classification

Every architectural rule should be classified before it becomes executable policy.

```text
HARD
  Product/security/provenance/legal-quality invariant.
  Fail closed by default. Do not weaken merely to unblock a change.

CONTROLLED
  Accepted architecture/product shape that may evolve through an explicit,
  documented design change with equivalent or stronger protection.

FLEXIBLE
  Private implementation detail. Avoid freezing it into architecture tests.

HISTORICAL
  Prior implementation, benchmark or migration evidence. Useful provenance,
  but not current architecture unless a current contract retains it.
```

The current custom agent harness is HISTORICAL/transition baseline infrastructure. Its semantic benchmark value is retained during migration, but its exact implementation shape must not be frozen as the target architecture.

## 3. What belongs in an architecture fitness test

A deterministic architecture test is appropriate when all are true:

1. the rule protects a named current guarantee;
2. violating it can be detected deterministically from repository/configuration structure;
3. the protected property is more stable than the implementation detail being inspected;
4. failure can explain the boundary and the supported recovery path.

Good candidates include:

- forbidden dependency direction;
- direct database access from agent/runtime code;
- provider contracts importing concrete provider implementations;
- architecture tests being removed from required CI;
- duplicate/conflicting guarantee IDs;
- repository instruction/source-of-truth drift;
- unsafe branch/integration workflow drift;
- future package boundaries once those packages become accepted architecture.

Bad candidates include:

- arbitrary file-count ceilings;
- forcing one class/function/module name forever;
- snapshots of every current package;
- style preferences already covered by Ruff/Pyright;
- stochastic model quality, which belongs in benchmarks;
- PostgreSQL concurrency/security properties that require real database evidence.

## 4. Current HARD boundaries

### 4.1 Primary source and evidence truth

Primary legal artifacts are authoritative. Model output is interpretation.

Architecture must preserve the ability to distinguish:

```text
source artifact/version
source/index claim evidence
observed destination/content evidence
derived interpretation
verification state
```

A framework trace or model response is not a replacement for durable evidence records.

### 4.2 Agent data access

Agents and provider runtimes must not receive generic SQL access or production database credentials.

Expected direction:

```text
agent/runtime
    -> typed tool/capability
    -> Document Workspace / Corpus API service
    -> deterministic authorization/validation
    -> persistence adapter
    -> PostgreSQL/object storage
```

Forbidden direction:

```text
agent/runtime -> psycopg / SQLAlchemy / raw production SQL
```

The current legacy ingestion package contains deterministic persistence adapters such as `observation_persistence.py`; this is not itself an agent boundary violation. Fitness tests therefore target agent/runtime surfaces, not every file under `ingestion/`.

### 4.3 Provider boundary

Provider contracts must remain independent of concrete providers.

Conceptually:

```text
provider contract
    <- concrete Gemini/OpenAI/etc adapter
    <- runtime/composition
```

Do not allow concrete provider SDK objects to become durable corpus/evidence DTOs.

### 4.4 Mandatory ingestion gates

The target canonical flow is:

```text
Structure Agent
    -> Structure Auditor
    -> Extraction Agent
    -> Extraction Auditor
    -> canonical commit
```

This is a business invariant, not a free-form handoff graph. Once implemented, job/state and integration tests must prove that canonical commit cannot bypass the required approvals.

Until those modules exist, architecture tests should protect the documented guarantee inventory rather than fake implementation-completeness assertions.

### 4.5 Tenant/security boundary

Tenant isolation, source membership, canonical-write permissions and production credentials are deterministic controls. They are not LLM guardrails.

Static fitness tests may protect dependency/credential boundaries. Runtime authorization and RLS/DB claims require dedicated invariant/adversarial evidence.

## 5. Current executable fitness functions

The first architecture-test set intentionally protects only stable rules that are meaningful in the current repository state.

### Guarantee inventory fitness

`backend/tests/architecture/test_current_guarantee_inventory.py`

Protects:

- unique semantic guarantee IDs;
- declared classifications/severities/evidence/risk vocabularies;
- HARD non-fitness guarantees requiring meaningful behavioral evidence classes;
- guarantee inventory not naming exact test files/paths.

### Agent/runtime connection-surface fitness

`backend/tests/architecture/test_agent_runtime_boundaries.py`

Protects:

- agent-like/runtime packages from importing direct DB drivers;
- the provider-neutral model contract from depending on concrete provider/runtime SDKs or database drivers.

The scan is intentionally semantic/path-role based rather than a snapshot of every current module.

### Repository governance and CI fitness

`backend/tests/architecture/test_repository_governance.py`

Protects:

- required normative architecture sources remain discoverable;
- root `AGENTS.md` points agents to the guarantee inventory/fitness-function policy;
- `.github/workflows/ci.yml` runs `tests/architecture` as an explicit required backend-quality step.

### Branch/integration workflow fitness

`backend/tests/architecture/test_branch_workflow_contract.py`

Protects the current controlled repository workflow:

- `main` is the canonical integration/deployable branch;
- normal work is represented by short-lived PR branches;
- CI retains the PR/main integration surface and `CI aggregate` gate;
- branch cleanup requires an actually merged PR, same-repository head, and protection of the default branch.

This intentionally does **not** copy Request Engine's `development -> main` topology because JurisNexo has no separate staging lifecycle that justifies that branch model today.

## 6. Fitness functions do not replace other evidence

Architecture tests answer questions such as:

> Can this dependency exist here?

They do not answer:

> Does this extraction correctly identify the holding?

or:

> Can tenant A access tenant B's rows under real PostgreSQL roles?

or:

> Does the new Structure Auditor improve boundary error detection?

Those require, respectively:

- semantic/legal benchmarks;
- real database security/invariant tests;
- targeted generator-verifier benchmarks.

The guarantee inventory identifies the evidence classes required for each guarantee.

## 7. Evolving an architecture test

A failing fitness function has only two legitimate dispositions:

```text
UNINTENTIONAL DRIFT
  change implementation to satisfy current accepted architecture

INTENTIONAL ARCHITECTURE EVOLUTION
  identify the protected guarantee
  update the normative architecture/ADR
  update the guarantee inventory if semantics changed
  adapt/replace the fitness function coherently
  preserve or strengthen evidence
  obtain exact-head CI
```

Do not widen an allowlist, weaken a scan, or delete a test simply because a legitimate feature now fails it.

Equally, do not keep an obsolete architecture assertion after the accepted architecture has changed. The guarantee matters more than the historical test shape.

## 8. Failure messages are an agent interface

Architecture-test failures should state:

```text
what boundary was crossed
which file/import/configuration crossed it
which current guarantee/policy is relevant
what supported surface should be used instead
whether changing the policy requires a documentation/ADR update
```

A future coding agent should be able to understand the design problem from CI output without reverse-engineering the test implementation.

## 9. CI contract

Architecture fitness functions are blocking tests in the normal PR CI path.

The canonical backend-quality lane must run:

```text
pytest tests/architecture
```

before the final `CI aggregate` can succeed.

Exact-head GitHub CI is authoritative merge evidence. A local or stale run is not proof for the current PR head.

## 10. How to add a new guarantee

Before adding a rule, write down:

```text
guarantee ID
statement
classification
severity
risk
required evidence class
plausible defect/failure mode
which evidence belongs in fitness vs invariant vs benchmark tests
```

Then add the smallest deterministic fitness test that protects the structural portion of that guarantee.

Do not create an architecture test simply because a pattern looks aesthetically preferable.

## 11. Long-term target

As the documented architecture becomes implemented, add fitness functions incrementally for accepted boundaries such as:

- Corpus API/domain/persistence dependency direction;
- agent runtime adapter isolation;
- canonical commit only through approved application services;
- research agents read-only against canonical source records;
- framework DTOs not leaking into durable evidence models;
- package dependency cycles;
- path-local `AGENTS.md` rules when subsystems become large enough to justify them.

Each addition should correspond to a real protected guarantee and a plausible regression, not architectural ceremony.
