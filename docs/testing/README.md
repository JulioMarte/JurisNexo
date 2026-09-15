# JurisNexo — Testing and Guarantee Evidence

## Purpose

JurisNexo separates four different questions:

```text
what must remain true?          -> current-guarantees.toml
what currently proves it?       -> current-proof-map.toml
how must proof be authored?     -> evidence-authoring-guide.md + backend/tests/AGENTS.md
why did proof change shape?      -> test-architecture-migration.md
```

The normative guarantee inventory is `docs/testing/current-guarantees.toml`. It names durable guarantees, classification, severity, and required evidence classes without freezing exact test filenames.

`docs/testing/current-proof-map.toml` is deliberately **non-normative**. It records representative current proofs and explicit evidence gaps. Test paths may move or be replaced without changing a guarantee, but a guarantee must never silently disappear between documentation and executable proof.

`docs/testing/test-architecture-migration.md` is also non-normative migration evidence. It records KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL decisions when tests, benchmarks, or execution boundaries are reorganized, especially during the custom-harness -> Agents SDK migration.

The core rule is:

> A green test is evidence only when a plausible defect in the claimed guarantee would make it fail.

## Canonical testing documents

- `current-guarantees.toml` — **normative** durable semantic guarantee inventory.
- `current-proof-map.toml` — non-normative map of representative proof plus explicit evidence debt.
- `test-architecture-migration.md` — non-normative ledger explaining why durable proof moves, changes, is replaced, or becomes historical.
- `repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL repository and proof governance.
- `evidence-authoring-guide.md` — normative workflow for falsifiable evidence, provenance, PostgreSQL/security boundaries, independent oracles, and benchmark integrity.
- `backend/tests/AGENTS.md` — operational rules for test authors and coding agents.
- `docs/22-architecture-fitness-functions.md` — executable architecture policy.

`AGENTS.md` files are operational maps. Durable rationale and contracts belong under `docs/`.

## Rigidity model

Every durable assertion is classified as:

```text
HARD        legal/security/provenance invariant or semantic boundary; fail closed
CONTROLLED  accepted architecture/product/repository shape; deliberate evolution only
FLEXIBLE    private implementation shape; do not freeze gratuitously
HISTORICAL  prior benchmark/release/design provenance; not automatic current authority
```

A legitimate feature may change a FLEXIBLE filename/helper/split without an architecture decision. A HARD provenance, security, legal-quality, or authority guarantee cannot be silently weakened because current implementation fails it.

## Evidence classes

`fitness` proves deterministic repository/architecture constraints. `invariant` proves durable correctness at the real authority boundary. `contract` proves supported API/schema/state semantics. `adversarial` proves rejection of plausible failure modes. `benchmark` proves stochastic/semantic quality against independent controlled inputs/gold. `integration` proves multi-stage/component behavior. `security` proves the real authorization/tenant/credential boundary.

Physical location answers **who owns/runs the proof**. Evidence classes answer **what it proves**.

## Current-proof map and evidence debt

Every guarantee must appear in one of two states in `current-proof-map.toml`:

```text
[[proofs]] -> representative current evidence exists
[[gaps]]   -> guarantee is accepted but required evidence is incomplete
```

A guarantee may have both representative proof and an explicit gap when some required evidence classes are still missing.

A gap is not a failure of honesty and must not be hidden. It is explicit technical/evidence debt. Each gap names the missing evidence classes and explains what is not yet proven.

Do not mark a guarantee covered merely because a nearby unit test exists. The representative proof must exercise the mechanism needed for the claimed evidence. Static fitness does not become runtime security evidence; a scorer smoke test does not become legal-semantic validation; a unit authorization helper test does not automatically prove end-to-end tenant isolation.

`backend/tests/architecture/test_current_proof_map.py` enforces that every current guarantee is mapped or explicitly gapped, every required evidence class is either represented or explicitly missing, and representative proof paths still exist. It intentionally does **not** make those paths permanent architecture.

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
update proof map / evidence gap when coverage meaning changed
        ↓
record KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL when restructuring proof
        ↓
run owning canonical CI / benchmark lane
        ↓
require exact-head evidence before merge
```

Do not start from “what assertion makes this implementation green?”. Start from the guarantee and the defect the proof must detect.

## Legal evidence discipline

Preserve the distinction between:

```text
primary legal source
source artifact/version/checksum
observed page/passage/content evidence
model-derived interpretation
canonical persisted conclusion/report
```

Model output is never an independent oracle for source truth. Gold for extraction/research benchmarks must remain independent from the candidate model execution.

## PostgreSQL and security evidence

When PostgreSQL semantics are part of the guarantee, use real PostgreSQL. Do not claim constraints, transaction semantics, locking, migration correctness, durable state, or runtime authorization from mocks or SQLite.

Direct SQL may establish valid prerequisites, inspect authoritative state, or directly prove a database backstop. It must not pre-create the final application result, disable enforcement, or manufacture a state unavailable through accepted authority unless the test specifically proves rejection of that impossible state.

When tenant/runtime authorization is part of the claim, execute the operation through the real supported runtime/application authority boundary. A privileged setup connection does not prove runtime restriction.

## Benchmark integrity

A workflow exiting successfully is not semantic success. Keep separate:

```text
runtime/provider status
navigation/mechanical status
semantic/evidence status
overall benchmark/product status
```

Do not leak gold into prompts/tools. Do not weaken scorers solely to make a candidate pass. If the benchmark contract is wrong or ambiguous, change/version it explicitly and retain the reason and adversarial evidence.

## Current test organization

The tree remains intentionally small:

```text
backend/tests/architecture/  repository/dependency/instruction/CI fitness functions
backend/tests/integration/   multi-component/application/database behavior
backend/tests/unit/          isolated logic
```

Do not create `db/`, `e2e/`, `fixtures/`, or other directory families merely to imitate another repository. Create them only when real proof ownership makes the current tree ambiguous or harmful.

## Removing or restructuring proof

Before deleting, weakening, moving, replacing, or consolidating meaningful evidence, give the protected guarantee one explicit disposition:

```text
KEEP        guarantee and proof remain valid
ADAPT       guarantee remains; proof changes with architecture/execution boundary
REPLACE     old proof is superseded by equal/stronger evidence
REMOVE      guarantee no longer applies and normative docs explicitly say why
HISTORICAL  proof remains only as provenance for a prior state/version
```

Never weaken a test solely because implementation currently fails it. When representative evidence changes, update the non-normative proof map. When durable proof changes execution boundary or status, record the reasoning in the migration ledger. Temporary duplicate evidence is preferable to a silent evidence hole.

## Current CI

`backend/tests/architecture/` contains blocking deterministic fitness functions. The backend-quality job runs them explicitly with `pytest tests/architecture`, and the broader PostgreSQL-backed suite also executes them.

That redundancy is intentional: architecture enforcement remains visible, while governance tests make accidental removal detectable.

Tests inspecting repository-level policy receive `JURISNEXO_REPO_ROOT`; PR topology tests receive actual `GITHUB_BASE_REF` and `GITHUB_HEAD_REF` values.

A green architecture suite proves only the structural/governance boundaries it actually checks. It does not prove every semantic guarantee, research behavior, tenant path, or benchmark claim. The proof map must continue to expose gaps.

## Agent instruction hierarchy

Critical boundaries carry local `AGENTS.md` maps and lightweight Claude/Gemini adapters:

```text
docs/
backend/src/jurisnexo/
backend/migrations/
backend/tests/
```

Tool-specific `.github/instructions/*.instructions.md` files are adapters for scoped editor guidance. They do not own architecture. Canonical authority remains repository/local `AGENTS.md` plus current documents under `docs/`.

## External governance controls

Repository tests can validate committed CI workflow, observed PR topology, branch cleanup logic, documentation policy, test-authoring policy, proof-map integrity, and dependency boundaries. They cannot configure GitHub branch protection/rulesets or prevent a direct push when the hosting platform still allows one.

Required status checks, PR-only merge policy, force-push prohibition, and protected long-lived branches must therefore be verified/configured at GitHub as external controls. Do not claim pytest proves those remote settings.

## Review questions

Before accepting a new or changed durable proof, answer:

1. What guarantee/risk does it protect?
2. What plausible broken implementation makes it fail?
3. Is the asserted detail HARD/CONTROLLED or merely FLEXIBLE shape?
4. Is setup valid and independent from the expected result?
5. Is the real authority/mechanism exercised?
6. Is the oracle/gold independent?
7. Are authoritative outcome and important negative side effects inspected?
8. Is the proof map honest about what remains unproven?
9. If proof moved or changed status, is its disposition recorded?
10. Which canonical CI/benchmark lane owns the evidence?

If those questions cannot be answered, redesign the proof before treating it as evidence.
