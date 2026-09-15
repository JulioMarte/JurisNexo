# JurisNexo — Pre-Production Evolution and Adversarial Proof Policy

Status: **normative while JurisNexo remains pre-production without customer-owned production corpus commitments or an externally promised compatibility contract**.

## 1. Purpose

JurisNexo is still learning which agent, ingestion, retrieval, corpus, and evidence boundaries are correct. Early benchmark checkpoints and the current custom harness are valuable because they preserve evidence about what worked and failed. They are not a permanent ceiling on the architecture.

The repository therefore follows one governing rule:

```text
freeze the evidence, not the future
```

A previous benchmark, test layout, provider adapter, schema shape, agent class, prompt, or harness may remain reproducible historical evidence without becoming an obligation for current product code to preserve its incidental structure.

This freedom is not permission to weaken provenance, legal-source fidelity, tenant isolation, canonical-write authority, benchmark independence, or other accepted HARD guarantees.

## 2. Current repository mode

Until JurisNexo stores customer-owned production data or commits to an external compatibility surface, the repository should optimize for one coherent trustworthy present-day system rather than preserving accidental MVP archaeology.

Current implications:

- CONTROLLED product and repository shape may evolve deliberately;
- FLEXIBLE implementation details may change without constitutional treatment;
- HARD semantic/security/provenance guarantees remain fail-closed unless replaced by an equal-or-stronger explicit contract;
- HISTORICAL evidence remains attributable to the checkpoint it actually proves;
- the custom harness may be retired capability by capability when the Agents SDK replacement proves equal-or-stronger relevant behavior;
- green CI is necessary merge evidence but does not by itself prove legal-semantic benchmark parity.

## 3. What historical evidence means

Historical evidence answers questions such as:

```text
what exactly did this benchmark checkpoint prove?
which source/gold/model/provider/configuration produced this result?
what did the custom harness do at this recorded revision?
what failure motivated the newer architecture?
```

It does not automatically answer:

```text
what must current JurisNexo look like internally?
which provider/runtime must current product code preserve?
which old filename/test inventory must still exist?
```

Frozen benchmark gold, source checksums, recorded scorer inputs, migration/release artifacts, and checkpoint reports should remain reproducible when they are meaningful provenance. Current product behavior may evolve beyond them through explicit contract and evidence disposition.

## 4. Test authority hierarchy

Durable tests should be interpreted by the risk they protect, not by age or filename.

### 4.1 HARD invariant/security/provenance proof

Preserve or strengthen evidence protecting properties such as:

```text
primary-source identity and checksum provenance
evidence/page/artifact membership
canonical-write audit gates
tenant isolation and authorization
least privilege / agent-data authority boundaries
atomicity and no-partial-write behavior
reproducible durable lineage
benchmark gold independence
claim/source traceability
```

If implementation boundaries change, adapt or replace the proof; do not silently retire the guarantee.

### 4.2 Contract proof

Contract tests protect intentionally supported API, schema, typed evidence, state-machine, capability, or caller semantics.

Before external compatibility commitments exist, a superior documented current contract may intentionally replace an internal/pre-production contract. Update the contract proof coherently instead of preserving an obsolete assertion solely because it once passed.

### 4.3 Architecture fitness functions

Architecture tests are blocking alarms against unreviewed drift. They should protect stable boundaries such as:

```text
agent/runtime code cannot silently gain database authority
mandatory orchestration gates remain explicit
instruction hierarchy remains routed to canonical authority
CI keeps blocking architecture proof visible
branch/integration topology remains serialized
historical/release proof does not masquerade as current architecture
```

Architecture fitness must not freeze exact file counts, every helper/class name, one provider inventory, or other FLEXIBLE shape unless that shape is itself an accepted contract.

### 4.4 Historical proof

Historical proof is pinned to a prior benchmark/release/implementation checkpoint. It should reproduce that checkpoint where valuable, without requiring current product head to preserve old internals.

### 4.5 Snapshot/allowlist/shape proof

Exact inventories have the lowest semantic authority. They are useful only while the exact inventory is normative. Prefer open-world rules that inspect newly discovered relevant code rather than allowlists that let new code escape enforcement or block legitimate additions.

## 5. Required disposition when proof changes

Any meaningful current proof removed, moved, consolidated, replaced, or moved out of blocking CI must receive one explicit disposition:

```text
KEEP        guarantee and proof remain current
ADAPT       guarantee remains; execution/architecture boundary changed
REPLACE     equal-or-stronger proof supersedes the old proof
REMOVE      guarantee genuinely no longer applies and current docs say why
HISTORICAL  proof now answers a prior-checkpoint question only
```

For `ADAPT`, `REPLACE`, or `REMOVE`, record where the protected intent is proven after the change. Use `docs/testing/test-architecture-migration.md` for migrations/restructuring and update `docs/testing/current-proof-map.toml` when representative current proof or evidence gaps change.

Deleting assertions because implementation currently fails them is not a valid disposition.

## 6. Adversarial proof philosophy

The purpose of high-value CI is to falsify unsafe or unsupported designs, not merely reward conformance to repository shape.

For state-changing, authority-sensitive, provenance-sensitive, or legal-evidence-sensitive capabilities, ask at least:

```text
What if the caller supplies a foreign-tenant or foreign-artifact identifier?
What if evidence points to the wrong page/source/checksum?
What if an audit gate is skipped or replayed?
What if two actors/jobs race to commit authoritative state?
What if the operation fails after partial work?
What if the same job/command is retried?
What if model output contradicts the primary source?
What if the benchmark candidate can infer/leak the gold answer?
What if a provider lacks a capability the agent role assumes?
What must remain reconstructable after mutable state changes?
```

Prefer a smaller number of strong adversarial/invariant proofs at the real authority boundary plus targeted unit/contract tests for localization.

## 7. PostgreSQL and authority evidence

When the protected property is owned by PostgreSQL or an application/database authority boundary, prove it there.

Do not substitute:

```text
mocked repository -> for DB constraint/transaction proof
SQLite/in-memory state -> for PostgreSQL semantics
LLM guardrail -> for authorization/tenant isolation
single transaction -> for a concurrency race
HTTP status alone -> for canonical state/provenance correctness
```

Direct SQL may create valid prerequisites, inspect authoritative state, or prove a database backstop. It must not manufacture the result that the supported operation is supposed to create and then claim the operation was proven.

## 8. Legal and benchmark evidence

Primary legal sources outrank model interpretation. Benchmark gold must remain independent from the candidate execution.

Keep distinct:

```text
source artifact/version/checksum
observed source/page/passage evidence
model interpretation
canonical persisted conclusion
benchmark gold/reference answer
candidate model output
```

A successful workflow, valid JSON response, or scorer process exit is not semantic success. Benchmark reports should separate runtime/mechanical status from semantic/evidence status.

## 9. Current versus historical lanes

CI/evaluation should conceptually distinguish:

```text
CURRENT PRODUCT PROOF
  accepted current contracts and architecture

HISTORICAL / CHECKPOINT PROVENANCE
  reproducibility of an earlier benchmark/runtime/release when still valuable
```

Historical evidence must not prevent justified current evolution. Current product evidence must not weaken HARD guarantees to preserve historical compatibility.

JurisNexo does not need a physical `tests/historical/` tree until enough historical executable proof exists to justify that ownership surface. If introduced, `backend/tests/conftest.py` classifies it automatically as `historical` evidence.

## 10. Architecture-change evidence bundle

A change that intentionally supersedes a previous architecture/test restriction is merge-ready only when reviewers can answer:

```text
OLD RULE
What was previously required?

WHY INSUFFICIENT
What real product/correctness need makes it inadequate?

NEW CONTRACT
What is authoritative now?

GUARANTEE DISPOSITION
Which guarantees remain, strengthen, change, or retire?

TEST DISPOSITION
KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL

ADVERSARIAL PROOF
Which plausible defects attack the new design?

COMPATIBILITY DECISION
Which historical/current compatibility is actually required?

EXACT-HEAD EVIDENCE
Which CI/benchmark lanes ran against the intended head?
```

## 11. Rules that must not become arbitrary gates

Do not block a justified change solely because:

- an old snapshot contains fewer files, modules, agents, tools, or fields;
- a previous provider/harness used a different internal interface;
- an old benchmark fixture assumes obsolete implementation shape;
- a generated inventory changed;
- a test path or helper was renamed;
- a duplicated test is consolidated while equal-or-stronger evidence remains;
- an older design document scoped out a capability before the product need was understood.

These are prompts to reconcile contract and evidence, not reasons to preserve a weaker architecture.

## 12. HARD defaults

The following remain HARD unless an explicit newer contract replaces them with equal-or-stronger protection:

```text
primary-source/provenance integrity
tenant isolation and authorization
canonical commit authority and audit gating
explicit evidence membership/traceability
least privilege and bounded agent/data authority
atomic durable state transitions
benchmark/gold independence
reproducibility sufficient to explain consequential legal outputs
adverse/supporting authority obligations where the research contract requires them
explicit, bounded failure semantics
```

## 13. Exit condition

This pre-production freedom ends when JurisNexo has customer-owned production data or externally committed compatibility obligations.

Before that point, create a production-evolution policy covering at least:

```text
schema/data migration compatibility
API/capability versioning
rollback and roll-forward guarantees
data retention and legal provenance obligations
deprecation policy
customer-visible breaking changes
benchmark/model upgrade policy
support/release windows
```

At that point, “pre-production” is no longer an admissible reason for destructive evolution.
