# JurisNexo — Implementation Governance and Agent Execution

## 1. Purpose

This document defines how implementation agents should turn JurisNexo's accepted architecture into code without collapsing multiple research hypotheses, weakening provenance, or silently rewriting product contracts.

It is intentionally operational. Architecture remains defined by the owning documents; this file defines execution discipline.

## 2. Core implementation rule

Implement the smallest coherent slice that proves one layer or contract at a time.

Do not interpret "implement the docs" as permission to rewrite the whole repository in one branch.

Prefer a sequence such as:

```text
contract/schema cleanup
    -> runtime spike
    -> structure benchmark
    -> structure auditor
    -> extraction
    -> extraction audit
    -> Corpus API integration
    -> research runtime migration
    -> old harness retirement
```

Each phase should have an observable output, tests, and benchmark or contract evidence before the next phase depends on it.

## 3. Current migration target

The selected default MVP runtime is OpenAI Agents SDK.

The migration replaces generic runtime mechanics only after parity or improvement is shown. It does not replace:

- source acquisition;
- document/page workspace semantics;
- provenance/evidence models;
- corpus persistence;
- tenant/security invariants;
- benchmark gold/scorers;
- legal research completion rules;
- product API contracts.

The current harness remains a baseline until the relevant capability has a validated replacement.

## 4. Recommended workstream order

### Workstream A — evidence contract

Goal: remove ambiguity between claim-source evidence, observed destination/content evidence, and derived interpretation.

Required outcome:

- typed evidence objects;
- validators for source/page membership;
- explicit verification states;
- scorer updates with adversarial fixtures;
- schema/versioning decision documented.

Do this before relying on semantic benchmark results from the new runtime.

### Workstream B — SDK Structure Agent parity spike

Goal: reproduce the current document-exploration capability using OpenAI Agents SDK over existing document-domain tools.

Keep the initial tool set narrow.

Compare against the current harness under matched source/model/configuration where practical.

Required evidence:

- tool trace;
- structured output;
- source-backed evidence;
- token/model-call/cost reporting;
- navigation/semantic benchmark comparison;
- failure taxonomy.

### Workstream C — targeted discrepancy benchmark

Goal: prove that the agent can recognize and investigate index/destination/boundary disagreement rather than merely succeed on easy references.

Use an independent prompt and gold. Do not leak the expected observed location into the task.

### Workstream D — Structure Auditor

Goal: measure whether independent review improves structure/boundary/evidence quality.

Do not assume a verifier is useful merely because it sounds safer. Measure error-detection recall, false rejection, cost, and latency.

### Workstream E — full-decision extraction

Start with source-faithful reconstruction and page/span provenance.

Do not require deep Legal Elements, summaries, citation treatment, and all metadata in one first implementation.

Promote later layers only when the previous representation is stable enough to serve as evidence.

### Workstream F — Extraction Auditor

Verify source membership, boundary leakage, field support, semantic role, and unresolved regions.

Persist candidate, verified, rejected, and unresolved states distinctly where appropriate.

### Workstream G — Corpus API

Converge agents and workers on stable capability contracts instead of direct database access.

Internal Python services and HTTP/FastAPI endpoints should share semantics. MCP, if added later, wraps the same contract rather than becoming a second source of truth.

### Workstream H — research runtime

Only after the corpus/evidence surface is credible, migrate/build the root Research Agent and bounded specialists around:

- candidate retrieval;
- case analysis;
- citation traversal;
- adverse-authority search;
- later-treatment checks;
- gap assessment;
- claim verification;
- final report synthesis.

## 5. Keep hypotheses separable

Do not combine unrelated changes when attribution matters.

Examples that should usually be separate PRs/experiments:

- evidence-schema redesign versus agent runtime migration;
- runtime migration versus retrieval/reranker changes;
- Structure Agent versus Structure Auditor introduction;
- extraction versus Legal Elements enrichment;
- provider/model change versus prompt/agent-policy change;
- scorer correction versus benchmark prompt change.

A combined change is acceptable only when the components are inseparable and the PR explains why.

## 6. Definition of done by layer

A layer is not done because code exists.

### Runtime/tool layer

Done when:

- supported tool contracts are tested;
- provider/runtime failures are classifiable;
- usage/cost is observable;
- exact-head CI is green;
- target semantic benchmark is at least baseline-equivalent unless the branch is explicitly experimental.

### Structure layer

Done when:

- boundaries/index/anomaly outputs are evidence-backed;
- known discrepancy tasks are exercised;
- unsupported/invented evidence is rejected;
- structure uncertainty is representable.

### Extraction layer

Done when:

- reconstructed content remains traceable to source pages/spans;
- adjacent-case leakage has tests;
- required metadata accuracy is measured;
- unreadable/unknown content can remain unresolved.

### Audit layer

Done when:

- intentionally bad fixtures are detected;
- valid fixtures are not rejected at unacceptable rates;
- the auditor independently accesses source evidence;
- cost/latency overhead is known.

### Corpus API layer

Done when:

- authorization and identifier membership are enforced server-side;
- agents do not need raw production SQL;
- writes use explicit canonical commit paths;
- public/private corpus semantics are clear;
- durable schemas are runtime-independent.

### Research layer

Done when:

- supporting and adverse retrieval both occur where material;
- evidence records back final claims;
- completion/gap states are explicit;
- critical/adverse authority benchmarks are measured;
- real-user usefulness can be evaluated.

## 7. Benchmark promotion policy

Use three conceptual tiers as soon as data volume supports them:

```text
development set
validation/model-selection set
locked comparison test set
```

Do not repeatedly tune a prompt against a frozen comparison set and then treat the same score as generalization evidence.

For high-stakes benchmark items, independent legal review remains the target.

## 8. Runtime/provider decision policy

The SDK is selected because it removes generic harness work. It must remain replaceable.

Do not let SDK-specific object models leak into durable legal records.

For each role, choose the model based on:

- benchmark quality;
- required tool/structured/multimodal capabilities;
- provider failure behavior;
- context constraints;
- cost and latency.

Provider adapters must be capability-tested before being treated as production-compatible.

## 9. Documentation-change rule

If implementation exposes a durable architectural conflict, do not silently pick a new direction in code.

Classify the issue:

```text
implementation bug
missing implementation detail
ambiguous contract
documented decision no longer valid
new architecture decision
```

For the last three, update the owning document or add an ADR in the same coherent change.

Do not rewrite historical benchmark artifacts or accepted prior observations merely to make the current architecture look cleaner.

## 10. PR quality contract

Every implementation PR should answer:

```text
What documented contract is being implemented?
What was intentionally left out?
What old behavior is retained for comparison/compatibility?
What new invariant or evidence contract exists?
How was it tested?
Which benchmark hypothesis was exercised?
What exact SHA has passing CI?
What semantic/product risks remain?
Which follow-up workstream comes next?
```

## 11. Avoid false completion

The following are not sufficient completion evidence by themselves:

- green unit tests with no relevant integration/benchmark coverage;
- valid Pydantic output;
- an SDK run that terminates normally;
- lower token usage;
- fewer lines of code;
- one successful historical-document run;
- a verifier agreeing with the generator;
- retrieval metrics without critical/adverse authority analysis;
- impressive report prose.

The product goal is reliable, inspectable legal work that saves real users time without unacceptable critical misses.
