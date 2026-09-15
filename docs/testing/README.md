# JurisNexo — Testing and Guarantee Evidence

## Purpose

JurisNexo separates **what must remain true** from **which test currently proves it**.

The normative guarantee inventory is:

`docs/testing/current-guarantees.toml`

It names durable guarantees, their classification, severity, and required evidence classes. It intentionally does not map guarantees to exact test filenames because test organization may change without changing the protected property.

The core testing rule is:

> A green test is evidence only when a plausible defect in the claimed guarantee would make it fail.

## Canonical testing documents

- `current-guarantees.toml` — durable semantic guarantee inventory.
- `repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL repository and proof-governance rules.
- `evidence-authoring-guide.md` — normative workflow for falsifiable evidence, legal-source provenance, PostgreSQL/security boundaries, independent oracles, and benchmark integrity.
- `backend/tests/AGENTS.md` — path-specific operational rules for test authors and coding agents.
- `docs/22-architecture-fitness-functions.md` — executable architecture policy.

`AGENTS.md` files are operational maps. Durable rationale and contracts belong under `docs/`.

## Rigidity model

Every durable assertion should be understood as one of:

```text
HARD        legal/security/provenance invariant or semantic boundary; fail closed
CONTROLLED  accepted architecture/product/repository shape; deliberate evolution only
FLEXIBLE    private implementation shape; do not freeze gratuitously
HISTORICAL  prior benchmark/release/design provenance; not automatic current authority
```

A legitimate feature may change a `FLEXIBLE` filename/helper/split without requiring an architecture change. A `HARD` provenance/security/legal-quality guarantee cannot be silently weakened because the current implementation fails it.

## Evidence classes

### `fitness`

Deterministic repository/architecture evidence. Appropriate for dependency direction, supported connection surfaces, CI/governance contracts, provider/runtime isolation, branch topology, and instruction routing.

### `invariant`

Behavioral evidence that a durable correctness property holds at the real authority boundary. Use the actual database/application boundary when that is what owns the guarantee.

### `contract`

Typed/API/schema/state-machine evidence showing that supported callers receive promised semantics. Contract evidence alone is not enough for a critical behavioral invariant unless the guarantee is purely structural.

### `adversarial`

Negative evidence designed around a plausible defect: wrong tenant, wrong page/artifact membership, unsupported evidence, stale/replayed state, missing audit gate, contradictory source, gold leakage, or similar failure modes.

### `benchmark`

Independent task-quality evidence over frozen or otherwise controlled inputs/gold. Use for stochastic/semantic claims such as structure discovery, extraction accuracy, adverse-authority recall, navigation, or verifier value.

### `integration`

Evidence spanning multiple real components/stages, such as `Structure -> Audit -> Extraction -> Audit -> canonical commit`.

### `security`

Evidence run against the real authorization/tenant/credential boundary rather than an LLM guardrail or mock that cannot exercise the security claim.

## Contributor / agent evidence flow

For every durable test change:

```text
identify guarantee/risk
        ↓
classify HARD / CONTROLLED / FLEXIBLE / HISTORICAL
        ↓
name a plausible defect that must make the proof fail
        ↓
choose the real execution boundary needed to expose it
        ↓
build minimum complete valid preconditions
        ↓
choose an independent oracle/gold
        ↓
exercise the real mechanism under test
        ↓
assert authoritative outcome + important absence of side effects
        ↓
run narrow proof
        ↓
run owning canonical CI / benchmark lane
        ↓
require exact-head evidence before merge
```

Do not start from “what assertion makes this implementation green?”. Start from the guarantee and the defect the proof must detect.

## Legal evidence discipline

JurisNexo must preserve the distinction between:

```text
primary legal source
source artifact/version/checksum
observed page/passage/content evidence
model-derived interpretation
canonical persisted conclusion/report
```

Model output is not an independent oracle for source truth. For extraction/research benchmarks, gold must remain independent from the candidate model execution.

## PostgreSQL and security evidence

When PostgreSQL semantics are part of the guarantee, use real PostgreSQL in the repository CI environment. Do not claim constraint, transaction, locking, migration, durable state, or authorization correctness from mocks or SQLite.

Direct SQL may establish valid prerequisites, inspect authoritative state, or directly prove a database backstop. It must not pre-create the final application result or disable the mechanism being tested.

When tenant/runtime authorization is part of the claim, execute the operation through the real supported runtime/application authority boundary. A privileged setup connection does not prove runtime restriction.

## Benchmark integrity

A workflow exiting successfully is not proof of semantic success.

Keep distinct:

```text
runtime/provider status
navigation/mechanical status
semantic/evidence status
overall benchmark/product status
```

Do not leak gold answers into prompts/tools. Do not weaken scorers solely to make a candidate pass. If the benchmark contract is genuinely wrong or ambiguous, fix/version it explicitly and preserve the reason.

## Current test organization

The current tree is intentionally small:

```text
backend/tests/architecture/  repository/dependency/instruction/CI fitness functions
backend/tests/integration/   multi-component/application/database behavior
backend/tests/unit/          isolated logic
```

Do not create `db/`, `e2e/`, `fixtures/`, or other directory families merely to imitate another repository. Add them when real proof ownership requires them.

Physical location answers **who owns/runs the proof**. Pytest markers and the guarantee inventory answer **what evidence it provides**.

## Removing or restructuring proof

Before deleting, weakening, moving, or consolidating meaningful evidence, give the protected guarantee one explicit disposition:

```text
KEEP        guarantee and proof remain valid
ADAPT       guarantee remains; proof changes with architecture
REPLACE     old proof is superseded by equal/stronger evidence
REMOVE      guarantee no longer applies and normative docs explicitly say why
HISTORICAL  proof remains only as provenance for a prior state/version
```

Never weaken a test solely because implementation currently fails it.

## Current CI

`backend/tests/architecture/` contains blocking deterministic fitness functions.

The backend-quality job runs them explicitly as:

```text
pytest tests/architecture
```

The full PostgreSQL-backed backend test job also executes them with the repository root mounted read-only. This redundancy is intentional: the explicit architecture step keeps the gate visible, while the broader backend suite makes accidental removal easier to detect through governance tests.

Tests that inspect root-level governance/docs receive `JURISNEXO_REPO_ROOT` from CI instead of assuming the backend container contains the entire checkout. Pull-request topology tests also receive actual `GITHUB_BASE_REF` and `GITHUB_HEAD_REF` values.

Other guarantees are proven through integration/PostgreSQL tests and benchmark/scorer lanes. A green architecture suite means the tested structural boundaries remain intact; it does **not** mean every semantic guarantee is implemented or verified.

## External governance controls

Repository tests can validate committed CI workflow, observed pull-request topology, branch-cleanup logic, documentation policy, test-authoring policy, and dependency boundaries. They cannot configure GitHub branch protection/rulesets or prevent a direct push when the hosting platform still allows one.

Required-status checks, PR-only merge policy, force-push prohibition, and deletion protection must therefore be verified/configured at the GitHub repository/ruleset layer. Do not claim pytest proves those remote settings.

## Review questions

Before accepting a new or changed durable proof, answer:

1. What guarantee/risk does it protect?
2. What plausible broken implementation makes it fail?
3. Is the asserted detail HARD/CONTROLLED or merely FLEXIBLE shape?
4. Is setup valid and independent from the expected result?
5. Is the real authority/mechanism exercised?
6. Is the oracle/gold independent?
7. Are authoritative outcome and important negative side effects inspected?
8. Which canonical CI/benchmark lane owns the evidence?

If those questions cannot be answered, redesign the proof before treating it as evidence.
