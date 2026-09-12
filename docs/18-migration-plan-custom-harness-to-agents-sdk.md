# JurisNexo — Migration Plan: Custom Harness to OpenAI Agents SDK

## 1. Goal

Migrate generic agent-runtime responsibilities to OpenAI Agents SDK without losing the document-domain capabilities, provenance guarantees, diagnostic quality, or benchmark comparability built during the historical-bulletin experiments.

## 2. What is being replaced

Candidate custom runtime responsibilities to retire after parity is proven:

- generic model/tool decision loop;
- generic subagent invocation plumbing;
- provider-facing structured-generation orchestration;
- custom handoff/delegation protocol where equivalent SDK primitives suffice;
- generic tracing concerns duplicated by the SDK;
- runtime-specific context/budget mechanisms that exist only to compensate for the custom loop.

Do not delete these components first. Replace them incrementally and compare behavior.

## 3. What is being retained

Retain or refactor into framework-independent JurisNexo components:

- source acquisition and checksum validation;
- document representations/workspaces;
- physical/view/printed-page mappings where source semantics require them;
- page/image/OCR tools;
- evidence and provenance models;
- discrepancy investigation semantics;
- Corpus API/service layer;
- database models and constraints;
- job state machines;
- frozen gold datasets and scorers;
- cost/quality benchmark reporting;
- security and tenant authorization.

## 4. Migration phases

### Phase 0 — freeze baseline

Record the current benchmark artifacts and known outcomes before changing runtime behavior.

Keep distinctions between:

- semantic benchmark failure;
- navigation failure;
- provider/transport failure;
- incomplete generation;
- budget exhaustion;
- harness/runtime failure.

### Phase 1 — SDK spike

Build one SDK-based Structure Agent over the existing historical document workspace.

Expose only a minimal initial tool set:

```text
search_document
read_page
read_printed_page
read_pages
render_page_image
```

Do not add an auditor yet. First establish an apples-to-apples runtime comparison.

### Phase 2 — evidence contract cleanup

Replace ambiguous evidence fields/parallel page arrays with typed evidence objects that distinguish:

- index/source claim evidence;
- destination/content evidence;
- observed decision-start evidence;
- derived interpretations.

Update scorers before using semantic results as release gates.

### Phase 3 — structure auditor

Add an independent Structure Auditor with source access.

Benchmark whether it improves:

- boundary accuracy;
- discrepancy detection;
- false-confirmation rate;
- evidence correctness.

Track added cost and latency.

### Phase 4 — full decision extraction

Implement bounded full-decision extraction from approved structure.

Start with faithful text and basic metadata. Add deeper semantic layers only after the source reconstruction benchmark is stable.

### Phase 5 — extraction auditor

Introduce field/source verification and boundary-leak detection.

Persist verified and rejected candidate fields distinctly.

### Phase 6 — Corpus API integration

Route reads/writes through stable application services rather than direct agent access to database internals.

Ensure future research agents can consume the same case/evidence contracts.

### Phase 7 — retire superseded harness code

Delete generic custom runtime components only when:

- SDK implementation meets or exceeds protected benchmark metrics;
- CI covers the replacement;
- failure diagnostics remain adequate;
- evidence/provenance is not weakened;
- no production/document tools still rely on the old runtime contract.

## 5. Initial comparative benchmark

Use the existing February 1980 bulletin as one regression source, but do not let it become the only test.

Compare at minimum:

```text
Current custom harness
vs
OpenAI Agents SDK Structure Agent
```

under matched model/configuration where possible.

Record:

- references investigated;
- boundaries/anomalies found;
- trace-backed evidence;
- token usage;
- model calls;
- latency;
- provider failures;
- semantic/navigation scores;
- code/runtime complexity.

## 6. Required discrepancy benchmark

Create a separate benchmark for known difficult index/boundary discrepancies rather than hoping the general exploration agent samples them.

This benchmark should require investigation without leaking the gold answer into the prompt.

Measure whether the agent:

- reads the claimed destination;
- recognizes mismatch/ambiguity;
- inspects neighbors or delegates appropriately;
- preserves the source reference as printed;
- records observed location separately;
- reaches a trace-supported resolution or explicitly remains unresolved.

## 7. Provider portability

Do not rewrite JurisNexo around provider-specific response objects.

Create a narrow model/runtime configuration layer so each agent role can select a provider/model according to benchmark and cost.

If an SDK feature does not work equivalently with a non-OpenAI provider, document that limitation and benchmark the fallback rather than silently changing semantics.

## 8. Exit criteria

The migration is successful when:

- JurisNexo no longer maintains a generic agent framework;
- domain tools and evidence remain framework-independent;
- structure/extraction pipelines are independently benchmarkable;
- provider/model choice remains configurable;
- agents interact with stable corpus/document APIs;
- mandatory audit stages are explicit in job state;
- the old harness can be removed without losing protected capabilities.

Reducing lines of code alone is not an exit criterion.
