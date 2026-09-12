# Prompt — Implement JurisNexo's accepted architecture incrementally

You are an implementation agent working inside the JurisNexo repository. Your objective is to move the repository toward the accepted architecture documented under `docs/`, while preserving existing proven guarantees, benchmark comparability, and executable architecture constraints.

This is **not** permission to perform a monolithic rewrite. Implement the architecture through small, attributable, testable and benchmarkable workstreams.

## Mandatory operating rules

1. Read root `AGENTS.md` first and obey it.
2. Read `docs/19-documentation-crosswalk.md` before interpreting older documents.
3. Read `docs/21-implementation-governance-and-agent-execution.md` before planning work.
4. Read `docs/22-architecture-fitness-functions.md`, `docs/testing/README.md`, and `docs/testing/current-guarantees.toml` before changing architecture-sensitive code.
5. Treat `main` as the canonical integration branch.
6. Work from the latest `main` on a short-lived branch and PR.
7. Require exact-head `CI aggregate` before merge and delete the merged branch.
8. Do not claim architecture completion because CI is green.
9. Do not weaken provenance, evidence, security, benchmark, tenancy, or adverse-authority requirements merely to simplify implementation.
10. If accepted docs are ambiguous or demonstrably wrong, update the owning doc/ADR and executable policy coherently instead of silently inventing a new architecture in code.

## Architecture-guarantee gate — mandatory before coding

For the intended workstream, identify every relevant guarantee in `docs/testing/current-guarantees.toml`.

Record before implementation:

```text
Affected guarantee IDs
Classification: HARD / CONTROLLED / FLEXIBLE / HISTORICAL
Protected risk/failure mode
Required evidence classes
Existing evidence
Evidence this work must add/change
Architecture fitness functions affected
Owning normative docs/ADR
```

Rules:

- a `HARD` guarantee fails closed by default;
- a `CONTROLLED` architecture shape may evolve only through an explicit coherent architecture change;
- do not freeze `FLEXIBLE` implementation details into tests without a real risk;
- do not promote `HISTORICAL` harness/release shape back into current architecture merely because old tests exist;
- a green fitness test proves only its structural property, not semantic/legal/security correctness;
- when the protected property requires PostgreSQL, authorization, provider behavior, or semantic legal judgment, run the real evidence boundary rather than replacing it with a static check.

### When an architecture fitness test fails

There are only two legitimate dispositions:

```text
UNINTENTIONAL DRIFT
  -> repair the implementation to satisfy accepted architecture

INTENTIONAL ARCHITECTURE EVOLUTION
  -> identify the protected guarantee
  -> update the normative architecture/ADR
  -> update current-guarantees.toml if the durable semantics/evidence changed
  -> adapt/replace the fitness function coherently
  -> preserve or strengthen the protected evidence
  -> obtain exact-head CI
```

Do **not** mechanically weaken the test, widen an allowlist, hide a dependency behind a generic shared module, or remove the fitness function merely to make CI green.

When a workstream creates a new stable architectural boundary, add the smallest deterministic fitness function that protects the structural risk. Do not write architecture tests that assert future modules/classes exist before those capabilities are accepted and implemented.

## Primary architecture to implement

The target MVP pipeline is:

```text
source artifact
    -> immutable source/provenance workspace
    -> Structure Agent
    -> Structure Auditor
    -> approved structural hypothesis
    -> Extraction Agent
    -> Extraction Auditor
    -> Corpus API canonical commit
    -> optional reusable enrichment
    -> searchable corpus
    -> Research Agent + bounded specialists
    -> Claim/Evidence Auditor
    -> verified report
```

OpenAI Agents SDK is the default MVP agent runtime for generic agent/tool mechanics. It is not the legal system of record and it does not make model providers feature-equivalent.

JurisNexo continues to own:

- source acquisition and canonical identity;
- document/page workspace semantics;
- typed evidence/provenance;
- application/job orchestration;
- Corpus API contracts;
- PostgreSQL/object-storage persistence;
- authorization/tenancy;
- benchmarks and gold;
- legal research completion/verification contracts.

## First task: audit before modifying

Before writing code, execute or reproduce the reasoning in:

`prompts/repository-conformance-audit.md`

The audit must include the **Guarantee Coverage Matrix** from `current-guarantees.toml`. Use the audit to choose the **next smallest coherent implementation gap**. Do not assume everything described below is missing.

## Required implementation order

Use this order unless repository evidence proves a prerequisite is already complete or a different order is strictly required.

### Phase 1 — evidence contract hardening

Goal: make evidence semantically unambiguous before relying on new semantic agent benchmarks.

Implement/verify typed evidence that distinguishes:

```text
source/index claim evidence
observed destination/content evidence
derived interpretation
verification state
artifact/source version
page identities required by the source
```

Requirements:

- eliminate ambiguous implicit correspondence such as unrelated parallel page arrays;
- validate source/page membership deterministically;
- preserve original source errors instead of silently normalizing them;
- version persisted contracts when compatibility requires it;
- add adversarial scorer/tests for wrong mappings, invented evidence, unrelated extra pages, nearby resolutions, contradictory cases, and unresolved cases.

Do not modify a scorer simply to turn an existing benchmark green.

### Phase 2 — OpenAI Agents SDK Structure Agent

Goal: prove generic runtime machinery can be replaced without losing JurisNexo document-domain capabilities.

Implement an SDK-based Structure Agent over the reusable Document Workspace/tool boundary.

Start with the minimum useful tool surface, for example:

```text
search_document
read_page
read_pages
read_printed_page / resolve_printed_page
render_page_image when needed
inspect_neighbor_pages
```

Use typed/Pydantic structured outputs for JurisNexo-owned contracts. Do not persist SDK-specific objects as durable corpus/evidence state.

Benchmark against the existing custom harness under matched model/provider configuration where practical. Record tool calls, evidence inspected, model/provider/version, structured output, token/cost/model-call usage, failures, navigation status, and semantic/evidence status.

The old harness remains until the replacement reaches accepted parity/improvement.

### Phase 3 — targeted discrepancy/boundary benchmark

Use a targeted benchmark for difficult index/destination/boundary discrepancies.

Requirements:

- prompt identifies the investigation target without revealing gold;
- independent gold stays separate from prompt/runtime context;
- score whether the agent reads the claimed destination, recognizes mismatch, investigates neighbors/delegates appropriately, preserves the original printed reference, and reaches a trace-supported resolution or explicitly remains unresolved.

Do not rerun a broad stochastic benchmark hoping it happens to exercise the hard case.

### Phase 4 — Structure Auditor

Implement an independent auditor with source access. It must challenge, not merely summarize, Structure Agent output.

Prioritize:

- starts/ends and continuations;
- index-reference mismatch;
- duplicate/missing/repeated scans/pages;
- OCR-damaged names/numbers;
- adjacent-decision leakage;
- contradictory evidence.

Possible states:

```text
APPROVED
APPROVED_WITH_AMENDMENTS
MORE_INVESTIGATION_REQUIRED
REJECTED
SOURCE_QUALITY_BLOCKED
```

Benchmark verifier value separately: errors caught, false rejection, cost, latency and downstream quality gain. Do not keep a verifier merely because it sounds safer.

### Phase 5 — full-decision extraction

Implement extraction on one approved bounded decision at a time.

Prefer progressive layers:

```text
A. source-faithful text reconstruction
B. internal decision sections / semantic roles
C. metadata/entities
D. legal references/citations
E. deeper legal enrichment only when benchmarked
```

Requirements:

- page/span provenance survives reconstruction;
- unreadable regions remain explicit;
- extraction cannot silently absorb neighboring decisions;
- party arguments, court reasoning, holdings, facts and dispositive text remain distinguishable when claimed;
- unknown values remain unknown rather than fabricated.

Do not require one giant one-shot schema for all legal understanding.

### Phase 6 — Extraction Auditor

Verify material extraction against source evidence.

At minimum test:

- source membership;
- boundary leakage;
- date/number/party support;
- dispositive correctness;
- party-argument versus holding/reasoning role;
- citation presence;
- unresolved OCR/source gaps.

Candidate, verified, rejected and unresolved states must not collapse into one canonical truth.

### Phase 7 — Corpus API convergence

Implement stable capability-oriented services so agents/workers do not need unrestricted database access.

Conceptual groups:

```text
documents.*
cases.*
citations.*
evidence.*
analysis.*
ingestion.*
```

Requirements:

- application/server controls authorization;
- IDs and artifact/page/case membership are validated;
- canonical writes use explicit approved commit paths;
- research agents cannot mutate canonical source facts;
- internal and HTTP/FastAPI surfaces preserve the same semantics;
- persisted records remain independent of the chosen agent SDK;
- MCP, if added later, wraps these contracts rather than creating a second semantics layer.

When this boundary becomes concrete, add architecture fitness functions protecting dependency direction and preventing agent/runtime code from acquiring persistence authority.

### Phase 8 — durable job-state integration

Required stages must be visible and persisted rather than hidden in logs:

```text
SOURCE_ACQUIRED / workspace ready
STRUCTURE_DISCOVERY_RUNNING
STRUCTURE_REVIEW_REQUIRED
STRUCTURE_APPROVED
EXTRACTION_RUNNING
EXTRACTION_REVIEW_REQUIRED
EXTRACTION_APPROVED
PERSISTING
COMPLETED
```

Include relevant blocked/failure/budget/cancel states.

Implement/verify idempotency, retry classes, cancellation, provider/runtime versus semantic failures, reproducibility snapshots, and prompt/model/tool/runtime/source/corpus versions.

Add integration/adversarial proof that canonical commit cannot bypass required audit states once the canonical path exists; a static architecture test alone is not sufficient.

### Phase 9 — retrieval baseline

Only claim retrieval features that actually exist and are benchmarked.

Maintain stable Search/Corpus API semantics over implementation details. Evolve components independently:

```text
exact/reference
metadata filters
PostgreSQL lexical/full-text
semantic retrieval where enabled
RRF/rank fusion
reranker only if justified
citation traversal
```

Do not introduce a graph database, ColBERT, SPLADE, dedicated BM25 engine or GraphRAG merely because docs mention them as future options.

### Phase 10 — research runtime

Build/migrate the root Research Agent over the normalized Corpus API.

Required behavior where applicable:

```text
question/brief decomposition
multiple retrieval strategies
candidate review
bounded Case Analyst delegation
citation traversal
adverse-authority search
later-treatment check
evidence aggregation
gap assessment
additional search if needed
claim verification
report synthesis
```

Logical specialist roles include Case Analyst, Citation Tracer, Adverse Researcher and Auditor / Claim Verifier.

Supporting and adverse authority must both be considered for material legal propositions. Subagents return structured findings/evidence; they do not independently publish the final user report.

### Phase 11 — product benchmark and pilot readiness

After technical layers are measurable, validate whether the product solves the lawyer's problem.

Track:

- Critical Authority Recall;
- Adverse Authority Recall;
- Critical Miss Rate;
- citation correctness;
- evidence completeness;
- additional human research required;
- time saved;
- repeated usage;
- willingness to pay/use again;
- cost per research job.

Do not interpret polished prose as product validation.

## Research methodologies: apply only to measured bottlenecks

Read `docs/17-agent-methodology-and-benchmark-map.md`.

Research influences include RLM, generator-verifier/critic, lexical+semantic+RRF, Legal Elements, HYPO/CATO, KELLER/LegalSearchLM, CaseGNN, CaseLink, RAPTOR, DocETL, LOTUS and GraphRAG/LegalGraphRAG.

Do not implement all of them.

For each proposed method, record first:

```text
Observed failure/bottleneck
Current/simple baseline
Method hypothesis
Metric expected to improve
Cost/latency/complexity introduced
Experiment/benchmark design
Adoption threshold
```

If it does not materially improve the relevant protected/product metric, do not promote it into production architecture.

## Provider/model discipline

Read `docs/20-agents-sdk-provider-and-guardrail-compatibility.md`.

Do not assume a provider is production-compatible because the SDK can invoke it. Verify each role's structured output, tool calls, agents-as-tools/handoffs, multimodal support, context limits, usage accounting, error/retry semantics, tracing, adapter maturity, cost and latency.

Use cheap models for high-volume work only when benchmarks prove they meet the required threshold.

## Guardrail discipline

Do not implement security or integrity as LLM-only guardrails.

Agent/SDK guardrails may protect semantic/runtime behavior. Application/API/database invariants must protect tenant scope, source/case/page identity, canonical write permission, artifact/checksum membership, state transitions, database constraints, quota/billing and production credentials.

## PR/workstream discipline

Use separate branches/PRs for hypotheses that need independent attribution. Normally separate evidence schema/scorer changes, SDK runtime migration, discrepancy benchmark, Structure Auditor, extraction, Extraction Auditor, Corpus API, retrieval changes, provider changes and research-agent changes.

Each PR must explain:

```text
Owning docs/contracts
Affected guarantee IDs + classifications
Required evidence classes and evidence added
Architecture fitness functions changed/added and why
What is implemented
What is intentionally deferred
Compatibility/baseline retained
New tests/benchmarks
Exact head SHA and CI status
Semantic benchmark result
Known risks/follow-up
```

If a PR changes a controlled architectural boundary, docs + guarantee inventory (when semantics/evidence change) + fitness function must evolve together.

## Testing and CI

Use the repository's real checks rather than substitutes.

The canonical CI includes:

- PostgreSQL-backed backend contract tests;
- Ruff;
- blocking `pytest tests/architecture` architecture fitness functions;
- Pyright strict;
- benchmark scorer smoke tests;
- Docker/API runtime smoke testing;
- final `CI aggregate`.

Run targeted tests while developing. Before completion, run the relevant architecture suite and require exact-head GitHub CI.

For claims involving provider behavior, document semantics, real PostgreSQL constraints, authorization, or paid model benchmarks, run the real boundary where feasible rather than claiming mocks/static fitness tests prove it.

## Stop conditions

Stop and report rather than silently changing standards if you discover:

- a HARD guarantee that cannot be implemented without changing product semantics;
- a fitness function whose protected guarantee is ambiguous or obsolete;
- a benchmark whose gold/scorer is ambiguous;
- a provider limitation that breaks the promised role contract;
- a security/tenant design conflict;
- a migration that would destroy historical evidence or benchmark comparability;
- missing independent legal gold needed for a reliability claim.

When this occurs, propose the smallest explicit doc/ADR/guarantee correction and evidence needed to resolve it.

## Completion criteria

You are not finished when "all files mentioned in docs exist."

A workstream is finished when:

- the owning documented contract is implemented coherently;
- affected HARD/CONTROLLED guarantees have the required evidence or explicitly documented remaining gaps;
- structural boundaries have appropriate blocking fitness functions without freezing incidental implementation shape;
- deterministic invariants remain enforced;
- relevant tests prove plausible defects;
- relevant semantic benchmark meets the agreed gate or experimental failure is clearly reported;
- exact-head CI passes;
- docs/ADR/guarantee inventory reflect any accepted architectural change;
- deferred work and remaining risks are explicit;
- the merged branch can be deleted and the next workstream can start from updated `main`.

Optimize for trustworthy, measurable legal work—not for maximizing framework features or test counts.
