# JurisNexo — Agent Methodology and Benchmark Map

## 1. Purpose

JurisNexo will not implement research papers as monolithic architectures. Research ideas are adopted only when they map to a concrete layer, failure mode, and measurable hypothesis.

This document prevents two common mistakes:

1. building unnecessary complexity because a technique is academically interesting;
2. claiming a technique improved JurisNexo without an independent benchmark showing what improved.

Every research line already referenced in the technical rationale must have an explicit product layer, a bounded implementation hypothesis, and a benchmark before it earns production complexity.

## 2. Layer-by-layer methodology map

| Layer | Primary problem | Methodology/pattern to adapt | What remains deterministic | Benchmark focus |
|---|---|---|---|---|
| Source acquisition | reliable artifact identity | reproducible acquisition/versioning | URL policy, checksum, timestamps, storage | source identity/replayability |
| Structure discovery | messy multi-decision documents | iterative tool-using LLM; RLM-style exploration | page/artifact addressing, tool permissions | boundary/index/anomaly accuracy |
| Structure verification | proposer may miss contradictions | generator-verifier / critic | stage gate, evidence membership | error-detection recall, false rejection |
| Full-text extraction | OCR/layout ambiguity | agentic multimodal reconstruction; DocETL-style staged transformation when justified | source/page provenance | text fidelity/completeness |
| Metadata extraction | noisy fields | structured extraction + verifier | schema and DB constraints | field precision/recall/F1 |
| Citation extraction | damaged legal references | specialized extraction/resolution agent; CaseLink-style citation awareness later | persisted citation identities/links | citation precision/recall |
| Legal enrichment | holdings/issues/elements | Legal Elements; HYPO/CATO-style factor/distinction representation | evidence links/versioning | proposition/element/factor accuracy |
| Query decomposition | long factual/legal prompts | KELLER/LegalSearchLM-style decomposition | query API, filter semantics | recall gain, critical/adverse recall |
| Case representation | long heterogeneous decisions | CaseGNN-style structural representation without requiring a GNN | case/page/section identity | retrieval/analysis gain vs flat text |
| Within-case retrieval | long decisions | RAPTOR-style hierarchical representations only if needed | evidence/page mapping | passage recall, latency, cost |
| Corpus retrieval | large corpus narrowing | lexical + semantic + RRF + optional reranker | search API/filter semantics | Recall@n, nDCG, Critical Authority Recall |
| Semantic data operations | aggregate filtering/joining over normalized corpus | LOTUS-style semantic operators where benchmarked | relational storage, authorization | quality/cost vs agent loops |
| Citation/corpus exploration | multi-hop precedent relations | CaseLink ideas; citation graph; GraphRAG/LegalGraphRAG only if justified | stored citation edges | multi-hop discovery gain vs cost |
| Case analysis | deep single-case understanding | bounded specialist; HYPO/CATO-style comparison where relevant | case/evidence API | evidence completeness/correctness |
| Deep research | iterative investigation | RLM-style root + bounded subagents | Corpus API, job/budget rules | critical/adverse recall, usefulness |
| Research verification | unsupported synthesis | independent claim/evidence auditor | evidence IDs, report gate | citation correctness, critical miss rate |

## 3. Recursive Language Model influence

RLM-style ideas are useful where a task is too large or messy for one static context:

- root model chooses programmatic investigations;
- large external state stays outside model context;
- subagents receive bounded tasks;
- results return as compact structured observations;
- investigation iterates until the task contract is satisfied or a budget/quality limit is reached.

Use this for difficult document exploration and deep legal research. Do not interpret it as a requirement to load an entire corpus into Python or to let a model replace search/query services.

Benchmark against a simpler non-recursive baseline on task quality, cost, latency, and evidence traceability.

## 4. Generator-verifier pattern

The default high-value pattern is independent proposal and review:

```text
Structure Agent -> Structure Auditor
Extraction Agent -> Extraction Auditor
Research synthesis -> Claim/Evidence Auditor
```

The verifier should have access to source evidence and should not rely only on the generator's summary.

Measure verifier value separately:

- material errors caught;
- correct outputs incorrectly rejected;
- additional tokens/cost;
- latency;
- net improvement in downstream quality.

If a verifier adds cost without improving protected metrics, remove or narrow it.

## 5. Hybrid retrieval and rank fusion

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

## 6. Legal Elements

Legal Elements-style extraction is a deep enrichment layer, not an ingestion prerequisite.

Evaluate it on whether structured elements improve:

- retrieval of factually analogous decisions;
- comparison across decisions;
- explanation of distinctions;
- adverse-authority discovery;
- report usefulness.

Every extracted element should preserve evidence and model/version metadata.

## 7. HYPO / CATO-style factor reasoning

Adapt the useful concept: precedent comparison should make material similarities and distinctions explicit instead of relying only on embedding similarity.

MVP implementation hypothesis:

- Case Analyst extracts material facts/factors with evidence;
- comparison jobs identify shared and distinguishing factors;
- factors remain model-generated, versioned, and reviewable rather than becoming hidden canonical truth.

Do **not** build a full hand-authored factor ontology before the pilot proves that factorized comparison improves lawyer outcomes.

Benchmark:

- fact-pattern retrieval improvement;
- distinction accuracy;
- legal reviewer usefulness;
- adverse-authority discovery;
- false similarity reduction.

## 8. KELLER / LegalSearchLM-style query decomposition

A long user fact pattern should not be represented by one embedding/query alone.

The Research Agent may derive multiple bounded search formulations for:

- legal issues;
- factual predicates;
- procedural posture;
- statutes/articles;
- desired and adverse outcomes;
- known terminology/citations.

The Search API remains deterministic; the model proposes queries, not database execution semantics.

Benchmark decomposition against single-query baselines using Critical Authority Recall, Adverse Authority Recall, Recall@K, cost, and search count.

## 9. CaseGNN-style structural case representation

Adopt the insight that a judgment has internal structure — facts, issues, party arguments, reasoning, holdings, outcome, citations — and that retrieval/analysis can benefit from those roles.

Do not introduce a graph neural network merely because the paper uses one.

Initial hypothesis:

- persist evidence-backed structural sections;
- index/selectively embed role-specific fields;
- compare against whole-case/chunk baselines.

Benchmark whether structural representations improve retrieval, case comparison, and role-confusion rates.

## 10. CaseLink / citation-aware retrieval

Citation links are first-class legal signals.

Initial implementation:

- extract and resolve explicit citations;
- expose `get_citations` and `get_citing_cases`;
- use citation relationships as optional retrieval/ranking/exploration features.

Later CaseLink-like learned graph ranking is justified only if explicit citation traversal/ranking leaves measurable discovery gaps.

Benchmark multi-hop authority discovery, later-treatment discovery, and critical-authority recall against non-citation baselines.

## 11. RAPTOR-style hierarchical long-document retrieval

Long decisions may require both local passages and whole-decision context.

Do not precompute hierarchical summaries for the entire corpus initially.

Trigger evaluation only if within-case search benchmarks show that flat page/passage retrieval misses relevant reasoning because of long-range context.

Possible adaptation:

- source-faithful pages/passages remain canonical evidence;
- hierarchical summaries are derived navigation aids;
- summaries must retain links to underlying evidence;
- the agent can descend from summary/section to exact source passages.

Benchmark passage recall, answer/evidence correctness, token use, and latency against flat within-case retrieval.

## 12. DocETL-style model-assisted transformation

DocETL is relevant to exhaustive corpus transformation, especially when heterogeneous documents need multiple semantic processing stages.

Our initial ingestion pipeline already adopts the useful idea of staged transformations:

```text
structure -> audit -> extraction -> audit -> enrichment
```

Do not adopt a separate DocETL runtime merely for architectural similarity. Evaluate direct use only if our pipeline becomes hard to maintain, parallelize, optimize, or evaluate at scale.

Benchmark throughput, extraction completeness, cost, failure recovery, and maintainability against the existing worker pipeline.

## 13. LOTUS-style semantic operators

LOTUS-like semantic filter/join/top-k/aggregation may be valuable after the corpus is normalized.

Examples:

- semantically filter a bounded candidate table;
- compare propositions across selected cases;
- semantically join structured issues/facts where deterministic keys do not exist.

These operators must operate over bounded authorized datasets and must not replace stable SQL/search contracts.

Benchmark them against equivalent bounded agent loops and deterministic+reranker alternatives on quality, token cost, latency, and reproducibility.

## 14. GraphRAG / LegalGraphRAG

Citation relations naturally form a graph, but that does not imply a dedicated graph database or GraphRAG pipeline is needed immediately.

Use PostgreSQL citation edges first.

Introduce graph-specific methods only after a benchmark identifies a failure that simpler citation traversal cannot solve, such as:

- multi-hop authority discovery;
- community/topic exploration;
- corpus-level precedent relationships;
- temporal citation-treatment analysis;
- global jurisprudential synthesis.

Compare against the non-graph baseline before adopting both the method and any new graph infrastructure.

## 15. Agent-runtime evaluation

OpenAI Agents SDK is the selected MVP runtime, but runtime choice itself remains benchmarkable.

A runtime migration must not be declared successful because it reduces code.

Compare:

- semantic task quality;
- evidence traceability;
- model/provider portability;
- structured-output reliability;
- multimodal/tool capability compatibility;
- token/cost usage;
- latency;
- failure diagnosability;
- implementation complexity;
- operational maintainability.

The custom harness remains a temporary comparison baseline during migration.

## 16. Benchmark hierarchy

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

### Level 5 — retrieval and query formulation

- relevant/critical/adverse authority discovery;
- single-query vs decomposed-query comparison;
- flat vs structured representation;
- citation-aware vs non-citation retrieval.

### Level 6 — case analysis

- holdings;
- facts;
- legal issues/elements;
- material factors/distinctions;
- source support.

### Level 7 — corpus exploration

- multi-hop authority discovery;
- later-treatment discovery;
- graph/hierarchical method incremental value.

### Level 8 — end-to-end research

- answer usefulness;
- critical/adverse coverage;
- citation correctness;
- time saved;
- additional human research required.

## 17. Research-to-product rule

A method earns production complexity only when it improves a product-relevant metric enough to justify its cost and maintenance.

Examples:

- a reranker is valuable if it materially improves critical/adverse authority recall;
- an auditor is valuable if it catches meaningful extraction/report errors with acceptable false rejection;
- KELLER-style decomposition is valuable if it finds authorities a simpler query strategy misses;
- HYPO/CATO-style factors are valuable if lawyers get better distinctions/comparisons;
- CaseGNN-style structure is valuable if role-aware representations improve retrieval or analysis;
- citation-aware/CaseLink methods are valuable if multi-hop or later-treatment discovery improves;
- RAPTOR-style hierarchy is valuable only if long-case passage retrieval improves enough to justify derived-summary complexity;
- DocETL or LOTUS is valuable only if it solves a measured transformation/semantic-operations bottleneck;
- GraphRAG is valuable only if it solves measured corpus-level exploration failures;
- a stronger model is valuable if protected legal metrics improve enough to justify spend.

The goal is not to reproduce papers. The goal is to build the simplest system that consistently solves the legal user's problem and can prove it with evidence.
