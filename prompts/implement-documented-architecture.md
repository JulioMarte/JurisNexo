# Prompt — Implement JurisNexo's accepted architecture incrementally

You are an implementation agent working inside the JurisNexo repository. Your objective is to move the repository toward the accepted architecture documented under `docs/`, while preserving existing proven guarantees and benchmark comparability.

This is **not** a permission to perform a monolithic rewrite. You must implement the architecture through small, attributable, benchmarkable workstreams.

## Mandatory operating rules

1. Read root `AGENTS.md` first and obey it.
2. Read `docs/19-documentation-crosswalk.md` before interpreting older documents.
3. Read `docs/21-implementation-governance-and-agent-execution.md` before planning work.
4. Treat `main` as the canonical integration branch.
5. Work from the latest `main` on a short-lived branch.
6. Use PRs and require exact-head `CI aggregate` before merge.
7. Delete merged branches; never reuse them for follow-up work.
8. Do not claim architecture completion because CI is green.
9. Do not weaken provenance, evidence, security, benchmark, or adverse-authority requirements merely to simplify implementation.
10. If accepted docs are ambiguous or demonstrably wrong, update the owning doc/ADR in the same coherent change instead of silently inventing a new architecture in code.

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

OpenAI Agents SDK is the default MVP agent runtime for generic agent/tool mechanics. It is not the system of record and it does not make model providers feature-equivalent.

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

Use that audit to determine the **next smallest coherent implementation gap**.

Do not begin by assuming everything described below is missing.

## Required implementation order

Use this order unless repository evidence proves a prerequisite is already complete or a different order is strictly required.

### Phase 1 — evidence contract hardening

Goal: make evidence semantically unambiguous before relying on new semantic agent benchmarks.

Implement/verify typed evidence that distinguishes at least:

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

Do not modify the scorer simply to turn an existing benchmark green.

### Phase 2 — OpenAI Agents SDK structure-agent spike

Goal: prove that generic runtime machinery can be replaced without losing JurisNexo's document-domain capabilities.

Implement an SDK-based Structure Agent over existing reusable document tools.

Start with the minimum tool surface needed, for example:

```text
search_document
read_page
read_pages
read_printed_page / resolve_printed_page
render_page_image when genuinely needed
inspect_neighbor_pages
```

Use Pydantic/typed structured outputs for JurisNexo-owned contracts.

Do not make durable corpus schemas depend on SDK-specific runtime objects.

Benchmark against the existing custom harness under matched model/provider configuration where practical.

Record:

- tool calls;
- evidence inspected;
- model/provider/version;
- structured output;
- token/cost/model-call usage;
- runtime/provider failures;
- navigation status;
- semantic/evidence status.

The old harness remains until this capability reaches accepted parity/improvement.

### Phase 3 — targeted discrepancy/boundary benchmark

Create a benchmark specifically for difficult index/destination/boundary discrepancies.

Requirements:

- prompt must identify the investigation target without revealing the gold resolution;
- independent gold must remain separate from the prompt;
- score whether the agent reads the claimed destination, recognizes mismatch, investigates neighbors/delegates as appropriate, preserves the original printed reference, and reaches a trace-supported resolution or explicitly remains unresolved.

Do not repeatedly rerun a general stochastic benchmark hoping it happens to exercise the hard case.

### Phase 4 — Structure Auditor

Implement an independent auditor with source access.

It must challenge, not merely summarize, the Structure Agent output.

It should prioritize:

- starts/ends;
- continuations;
- index-reference mismatch;
- duplicate/missing/repeated scans/pages;
- OCR-damaged names/numbers;
- adjacent-decision leakage;
- contradictory evidence.

Possible outputs should include:

```text
APPROVED
APPROVED_WITH_AMENDMENTS
MORE_INVESTIGATION_REQUIRED
REJECTED
SOURCE_QUALITY_BLOCKED
```

Benchmark verifier value separately:

- errors caught;
- false rejection;
- cost;
- latency;
- downstream quality gain.

Do not keep a verifier just because it sounds safer.

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
- party arguments, court reasoning, holdings, facts, and dispositive text remain distinguishable when claimed;
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

Candidate, verified, rejected, and unresolved states must not collapse into one canonical truth.

### Phase 7 — Corpus API convergence

Implement stable capability-oriented services so agents/workers do not need unrestricted database access.

Target conceptual groups:

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
- internal service calls and HTTP/FastAPI surfaces preserve the same semantics;
- persisted records remain independent of the chosen agent SDK;
- MCP, if added later, wraps these contracts rather than creating a second semantics layer.

### Phase 8 — durable job-state integration

Make required stages visible and persisted.

The ingestion state machine must represent the semantic gates, not hide them in logs:

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

Implement/verify:

- idempotency;
- retry classes;
- cancellation;
- provider/runtime versus semantic failure distinction;
- reproducibility snapshot;
- prompt/model/tool/runtime/source/corpus versions.

### Phase 9 — retrieval baseline

Only claim retrieval features that actually exist and are benchmarked.

Maintain a stable Search/Corpus API over implementation details.

Baseline should evolve through independently measured components:

```text
exact/reference
metadata filters
PostgreSQL lexical/full-text
semantic retrieval where enabled
RRF/rank fusion
reranker only if justified
citation traversal
```

Do not introduce a graph database, ColBERT, SPLADE, dedicated BM25 engine, or complex GraphRAG merely because the docs mention them as future options.

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

Logical specialist roles include:

- Case Analyst;
- Citation Tracer;
- Adverse Researcher;
- Auditor / Claim Verifier.

Supporting and adverse authority must both be considered for material legal propositions.

Subagents return structured findings/evidence. They do not independently publish the final user report.

### Phase 11 — product benchmark and pilot readiness

After technical layers are measurable, validate whether the product actually solves the lawyer's problem.

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

Current research influences include:

- RLM;
- generator-verifier / critic;
- lexical + semantic + RRF;
- Legal Elements;
- HYPO/CATO;
- KELLER/LegalSearchLM;
- CaseGNN;
- CaseLink;
- RAPTOR;
- DocETL;
- LOTUS;
- GraphRAG/LegalGraphRAG.

Do not implement all of them.

For each proposed method, write down before implementation:

```text
Observed failure/bottleneck
Current/simple baseline
Method hypothesis
Metric expected to improve
Cost/latency/complexity introduced
Experiment/benchmark design
Adoption threshold
```

If the method does not materially improve the relevant protected/product metric, do not promote it into the production architecture.

## Provider/model discipline

Read `docs/20-agents-sdk-provider-and-guardrail-compatibility.md`.

Do not assume a provider is production-compatible because the SDK can invoke it.

For every agent role, verify required capability:

- structured output;
- tool/function calls;
- agents-as-tools/handoffs;
- multimodal/PDF/image support;
- context limits;
- usage accounting;
- error/retry behavior;
- tracing;
- SDK adapter maturity;
- cost/latency.

Use cheap models for high-volume work only when benchmarks prove they meet the required quality threshold.

## Guardrail discipline

Do not implement security or integrity as LLM-only guardrails.

Agent/SDK guardrails may protect semantic/runtime behavior.

Application/API/database invariants must protect:

- tenant scope;
- source/case/page identity;
- canonical write permission;
- artifact/checksum membership;
- state transitions;
- database constraints;
- quota/billing;
- production credentials.

## PR/workstream discipline

Use separate branches/PRs for hypotheses that need independent attribution.

Normally separate:

- evidence schema/scorer changes;
- SDK runtime migration;
- discrepancy benchmark;
- Structure Auditor;
- extraction;
- Extraction Auditor;
- Corpus API;
- retrieval changes;
- model/provider changes;
- research-agent changes.

Each PR must explain:

```text
Owning docs/contracts
What is implemented
What is intentionally deferred
Compatibility/baseline retained
New tests/benchmarks
Exact head SHA and CI status
Semantic benchmark result
Known risks/follow-up
```

## Testing and CI

Use the repository's real checks rather than inventing substitutes.

The canonical CI currently includes PostgreSQL-backed backend contract tests, Ruff, Pyright strict, benchmark scorer smoke tests, Docker/API runtime smoke testing, and `CI aggregate`.

Run targeted tests while developing; require exact-head GitHub CI before merge.

For claims involving provider behavior, document semantics, real PostgreSQL constraints, or paid model benchmarks, run the real boundary where feasible rather than claiming mocks prove it.

## Stop conditions

Stop and report rather than silently changing standards if you discover:

- a documented invariant that cannot be implemented without changing product semantics;
- a benchmark whose gold or scorer is ambiguous;
- a provider limitation that breaks the promised role contract;
- a security/tenant design conflict;
- a required migration that would destroy historical evidence or benchmark comparability;
- missing independent legal gold needed to make a reliability claim.

When this occurs, propose the smallest explicit doc/ADR correction and evidence needed to resolve it.

## Completion criteria

You are not finished when "all files mentioned in docs exist."

You are finished with a workstream when:

- the owning documented contract is implemented coherently;
- deterministic invariants remain enforced;
- relevant tests prove plausible defects;
- relevant semantic benchmark meets the agreed gate or the experimental failure is clearly reported;
- exact-head CI passes;
- docs/ADR reflect any accepted architectural change;
- deferred work and remaining risks are explicit;
- the merged branch can be deleted and the next workstream can start from updated `main`.

Optimize for trustworthy, measurable legal work—not for maximizing the number of implemented framework features.
