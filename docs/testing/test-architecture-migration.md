# JurisNexo test-architecture migration ledger

Status: **active migration evidence; non-normative**.

This ledger records how durable proof evolves while JurisNexo moves from the current custom agent harness toward the OpenAI Agents SDK runtime and while repository testing becomes guarantee-driven.

Normative authority remains:

- `docs/testing/current-guarantees.toml` for what must remain true;
- `docs/testing/repository-governance-contract.md` for rigidity/evolution rules;
- `docs/testing/evidence-authoring-guide.md` for how proof is authored;
- current product/security/data/agent contracts under `docs/`.

`docs/testing/current-proof-map.toml` records representative present proof and explicit gaps. This migration ledger records **why proof changes shape**.

## 1. Disposition rule

A meaningful test, benchmark, scorer, or architecture fitness function may move, be consolidated, be replaced, or stop running in current CI only after its protected guarantee receives one explicit disposition:

```text
KEEP        guarantee and current proof remain valid
ADAPT       guarantee remains; proof changes because the architecture/execution boundary changed
REPLACE     old proof is superseded by equal-or-stronger current evidence
REMOVE      guarantee genuinely no longer applies and current normative docs say why
HISTORICAL  proof remains useful only to reproduce/explain a prior implementation or benchmark state
```

`REMOVE` is not a synonym for “the test is inconvenient”. `HISTORICAL` is not a dumping ground for tests that currently fail.

## 2. Migration invariant

The migration must not reduce evidence quality merely to simplify the repository or align it aesthetically with Request Engine.

The important equivalence is semantic:

```text
old proof shape may disappear
        BUT
protected guarantee + equal/stronger evidence must survive
```

Exact filenames, helper names, fixture layouts, custom-harness classes, and provider-specific adapter details are normally FLEXIBLE. Provenance, canonical-write authority, tenant isolation, benchmark independence, research verification, reproducibility, and agent/database authority boundaries are not.

## 3. Current KEEP decisions

The following current proof categories remain current-product evidence even if their physical organization evolves:

- source artifact identity, provenance and source-document inventory evidence;
- typed page/passage evidence and adversarial provenance validation;
- real-PostgreSQL canonical commit authority and no-write-on-rejection proofs;
- tenant/scope authorization proofs that protect current supported corpus paths;
- resolution/provenance ledger constraints;
- architecture fitness that prevents agent/runtime code from gaining unsupported database authority;
- branch/instruction/repository governance fitness functions;
- benchmark scorers that still measure a current accepted capability or provide a valid current baseline.

Historical names or origin in the custom harness do not make these guarantees historical.

## 4. Custom harness -> Agents SDK disposition policy

The runtime migration must distinguish implementation coupling from protected behavior.

### ADAPT

A custom-harness test should normally receive `ADAPT` when it protects a current guarantee but exercises that guarantee through a runtime-specific implementation surface that is being replaced.

Examples of guarantees that must survive adaptation:

```text
bounded tool/capability access
source/evidence provenance
mandatory ingestion audit ordering
structured result validation
provider/model configuration provenance
failure/retry semantics
benchmark budget/accounting where product-relevant
```

The adapted proof should target the stable JurisNexo capability/application boundary or the new Agents SDK adapter boundary, whichever actually owns the guarantee.

### REPLACE

A runtime-specific proof may receive `REPLACE` when a new test or benchmark demonstrates the same guarantee at a stronger or more realistic execution boundary. Record the representative replacement in `current-proof-map.toml` before retiring the old proof from current evidence.

### HISTORICAL

A custom-harness proof may become `HISTORICAL` only when it answers a prior-state question such as:

```text
what behavior/cost/quality did the old harness demonstrate at a recorded checkpoint?
```

Historical evidence must not force current production code to preserve obsolete runtime internals. Conversely, historical benchmark artifacts must not be rewritten to make the new runtime look better.

### REMOVE

Removal is valid only when the underlying guarantee is explicitly retired or proven redundant by equal/stronger current evidence and the normative/current proof records are updated coherently.

## 5. Current architecture-test direction

Architecture fitness should move away from exact repository snapshots and toward rules that remain true under legitimate growth.

Prefer:

```text
all discovered relevant code is inspected by the boundary rule
new agent/runtime paths cannot acquire DB authority silently
critical instruction boundaries retain local AGENTS routing
all guarantee evidence classes are proven or explicitly gapped
CI keeps deterministic architecture fitness visible and blocking
```

Avoid:

```text
exact number of files/modules/tests
one permanent list of every class or helper
provider/runtime implementation inventory as product architecture
path names treated as semantic guarantees without an ownership reason
```

## 6. Current evidence-gap checkpoint

The proof map currently records incomplete evidence rather than pretending full maturity. Important open categories include:

- full end-to-end enforcement of `Structure -> Structure Audit -> Extraction -> Extraction Audit -> commit`;
- runtime security proof that an agent/model cannot obtain unrestricted DB authority or production credentials;
- tenant isolation across the complete supported surface, not only current corpus/canonical-commit paths;
- verified legal research behavior including adverse authority and claim verification;
- complete run-level reproducibility across source/corpus/model/provider/prompt/configuration/job state;
- benchmark anti-gold-leak and scorer-governance fitness/adversarial proof;
- contract-level evidence that test metadata/CI selection preserve declared evidence meaning.

These gaps are accepted evidence debt, not accepted correctness failures. Work that claims one of these guarantees as complete must close or narrow the corresponding gap with real evidence.

## 7. Rules for future restructuring

When reorganizing tests or benchmarks:

1. identify the guarantee IDs affected;
2. classify each old proof with KEEP/ADAPT/REPLACE/REMOVE/HISTORICAL;
3. do not change product code merely to preserve a FLEXIBLE old test shape;
4. do not weaken HARD guarantees to preserve migration speed;
5. update `current-proof-map.toml` when representative evidence or evidence gaps change;
6. retain historical benchmark/gold provenance when needed for fair baseline comparison;
7. run the narrow proof and the canonical owning CI/benchmark lane;
8. require exact-head evidence before merge.

Temporary duplicate proof is preferable to a silent evidence hole while a guarantee is being moved between execution boundaries.

## 8. Promotion criteria for new test ownership surfaces

Do not add `backend/tests/db/`, `e2e/`, shared `fixtures/`, or other directory families because Request Engine has them.

Create a new physical test ownership surface only when at least one of these is true:

- the execution boundary is materially different from existing `unit/` or `integration/` ownership;
- independent suites genuinely need shared scenario builders;
- a public production-like journey has distinct ownership and selection semantics;
- PostgreSQL-specific invariant/race/security proofs become numerous enough that mixing them into generic integration tests obscures their authority.

The directory is a consequence of proof ownership, not the source of it.

## 9. Completion standard

A migration/refactor of test architecture is complete only when:

```text
current guarantee inventory remains coherent
representative proof map is honest
open evidence gaps are explicit
old proof received a disposition
new proof actually ran in the intended environment
canonical CI/benchmark lane proves the exact head
```

A lower test count, cleaner tree, or successful CI alone is not evidence that the migration preserved correctness.
