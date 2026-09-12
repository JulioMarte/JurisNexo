# JurisNexo — Agent Methodology and Benchmark Map

## 1. Purpose

JurisNexo will not implement research papers as monolithic architectures. Research ideas are adopted only when they map to a concrete layer, failure mode, and measurable hypothesis.

This document prevents two common mistakes:

1. building unnecessary complexity because a technique is academically interesting;
2. claiming a technique improved JurisNexo without an independent benchmark showing what improved.

## 2. Layer-by-layer methodology map

| Layer | Primary problem | Methodology/pattern to adapt | What remains deterministic | Benchmark focus |
|---|---|---|---|---|
| Source acquisition | reliable artifact identity | reproducible acquisition/versioning | URL policy, checksum, timestamps, storage | source identity/replayability |
| Structure discovery | messy multi-decision documents | iterative tool-using LLM; RLM-style exploration | page/artifact addressing, tool permissions | boundary/index/anomaly accuracy |
| Structure verification | proposer may miss contradictions | generator-verifier / critic | stage gate, evidence membership | error-detection recall, false rejection |
| Full-text extraction | OCR/layout ambiguity | agentic multimodal reconstruction | source/page provenance | text fidelity/completeness |
| Metadata extraction | noisy fields | structured extraction + verifier | schema and DB constraints | field precision/recall/F1 |
| Citation extraction | damaged legal references | specialized extraction/resolution agent | persisted citation identities/links | citation precision/recall |
| Legal enrichment | holdings/issues/elements | Legal Elements-style structured analysis | evidence links/versioning | proposition/element accuracy |
| Retrieval | large corpus narrowing | lexical + semantic + RRF + optional reranker | search API/filter semantics | Recall@n, nDCG, Critical Authority Recall |
| Case analysis | deep single-case understanding | bounded specialist agent | case/evidence API | evidence completeness/correctness |
| Corpus exploration | citation/relationship traversal | citation graph; GraphRAG only if justified | stored citation edges | discovery gain vs cost |
| Deep research | iterative investigation | RLM-style root + bounded subagents | Corpus API, job/budget rules | critical/adverse recall, usefulness |
| Research verification | unsupported synthesis | independent claim/evidence auditor | evidence IDs, report gate | citation correctness, critical miss rate |

## 3. Recursive Language Model influence

RLM-style ideas are useful where a task is too large or messy for one static context:

- root model chooses programmatic investigations;
- large external state stays outside model context;
- subagents receive bounded tasks;
- results return as compact structured observations;
- investigation iterates until the task contract is satisfied or a budget/quality limit is reached.

Do not interpret this as a requirement to load an entire corpus into Python or to let a model replace search/query services.

## 4. Generator-verifier pattern

The default high-value pattern is independent proposal and review:

```text
Structure Agent -> Structure Auditor
Extraction Agent -> Extraction Auditor
Research synthesis -> Claim/Evidence Auditor
```

The verifier should have access to the source evidence and should not rely only on the generator's summary.

Measure verifier value separately:

- errors caught;
- correct outputs incorrectly rejected;
- additional tokens/cost;
- latency;
- net improvement in downstream quality.

If a verifier adds cost without improving protected metrics, remove or narrow it.

## 5. Retrieval methodology

Start simple and measurable:

```text
exact/reference matching
+ PostgreSQL lexical baseline
+ semantic retrieval when useful
+ Reciprocal Rank Fusion
+ reranker only if benchmarks justify it
+ citation traversal
```

Do not prematurely replace the stable search service with agent-written scans.

Protected retrieval metrics should emphasize legal risk, not only average ranking:

- Critical Authority Recall;
- Adverse Authority Recall;
- Critical Miss Rate;
- Recall@20/50/100;
- nDCG;
- MRR.

## 6. Legal Elements and deep normalization

Legal Elements-style extraction is a deep enrichment layer, not an ingestion prerequisite.

Evaluate it on whether structured elements improve:

- retrieval of factually analogous decisions;
- comparison across decisions;
- explanation of distinctions;
- adverse-authority discovery;
- report usefulness.

Every extracted element should preserve evidence and model/version metadata.

## 7. GraphRAG and graph methods

Citation relations naturally form a graph, but that does not imply a dedicated graph database or GraphRAG pipeline is needed immediately.

Use PostgreSQL citation edges first.

Introduce graph-specific methods only after a benchmark identifies a failure that simpler citation traversal cannot solve, such as:

- multi-hop authority discovery;
- community/topic exploration;
- corpus-level precedent relationships;
- temporal citation-treatment analysis.

Compare against the non-graph baseline before adopting.

## 8. Agent-runtime evaluation

OpenAI Agents SDK is the selected MVP runtime, but runtime choice itself remains benchmarkable.

A runtime migration must not be declared successful because it reduces code.

Compare:

- semantic task quality;
- evidence traceability;
- model/provider portability;
- token/cost usage;
- latency;
- failure diagnosability;
- implementation complexity;
- operational maintainability.

The custom harness remains a temporary comparison baseline during migration.

## 9. Benchmark hierarchy

Build benchmarks bottom-up so failures can be attributed to a layer.

### Level 1 — document mechanics

- page identity;
- OCR/text accessibility;
- duplicate/printed-page handling.

### Level 2 — structure

- index detection;
- decision boundaries;
- discrepancy resolution;
- continuation handling.

### Level 3 — extraction

- full text;
- metadata;
- citations;
- semantic roles.

### Level 4 — verification

- unsupported claims;
- boundary leakage;
- evidence mismatch;
- role confusion.

### Level 5 — retrieval

- relevant/critical/adverse authority discovery.

### Level 6 — case analysis

- holdings;
- facts;
- legal issues/elements;
- source support.

### Level 7 — end-to-end research

- answer usefulness;
- critical/adverse coverage;
- citation correctness;
- time saved;
- additional human research required.

## 10. Research-to-product rule

A method earns production complexity only when it improves a product-relevant metric enough to justify its cost and maintenance.

Examples:

- a reranker is valuable if it materially improves critical/adverse authority recall;
- an auditor is valuable if it catches meaningful extraction/report errors with acceptable false rejection;
- a stronger model is valuable if it improves protected legal metrics enough to justify spend;
- GraphRAG is valuable only if it solves measured multi-hop/corpus exploration failures;
- deep normalization is valuable only if it improves retrieval, analysis, or lawyer usefulness.

The goal is not to reproduce papers. The goal is to build the simplest system that consistently solves the legal user's problem and can prove it with evidence.
