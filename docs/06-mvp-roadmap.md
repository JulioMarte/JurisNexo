# JurisNexo — MVP Roadmap

## 1. Roadmap principle

The roadmap should optimize for evidence of product value, not architectural completeness or raw document count.

The MVP should reach a point where real lawyers can submit real research questions, receive a verifiable report, and tell us whether it materially reduced their work.

Corpus growth follows the canonical two-speed strategy in `38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md`:

```text
broad official-source discoverability/searchability
        +
selective evidence-backed semantic depth
```

These tracks run in parallel. A source document does not need expensive legal-semantic normalization before it can contribute to coverage measurement, canonical resolution, retrieval, citation traversal or adverse-authority search. Conversely, broad acquisition must not be mistaken for trustworthy deep legal understanding.

The selected agent runtime is infrastructure. Roadmap milestones are defined by domain capabilities and measurable quality, not by framework adoption alone.

## 2. Phase 0 — repository and contracts

Deliverables:

- product vision;
- architecture contract;
- corpus/data model;
- research-agent contract;
- agent-runtime ADR and migration plan;
- ingestion agent/auditor pipeline contract;
- Corpus API contract;
- evaluation plan;
- security/privacy baseline;
- explicit open decisions;
- technology stack and deployment contract;
- CI/testing contract;
- pilot-corpus contract;
- two-speed corpus and jurisprudential-intelligence strategy.

Exit condition:

The team can explain what the MVP is, what it is not, how it will be built, what source material will be used first, how broad and deep corpus work differ, and how success will be measured without relying on unwritten assumptions.

## 3. Phase 1 — trusted ingestion proof and source inventory

Goal: prove that real Supreme Court source material can be turned into reliable searchable judicial records while preserving page-level provenance, while also establishing a reproducible inventory of the official source universe.

### Canonical deep-ingestion fixture

The first canonical ingestion fixture remains:

```text
Suprema Corte PDF/Principales_Decisiones_enero_abril_2025.pdf
```

This is a compilation and must not be modeled as one judicial case merely because it is one PDF.

The primary deep-ingestion risk is correctly transforming a compilation into individually identifiable, page-traceable decisions despite messy OCR/layout and uncertain document boundaries.

The default deep-ingestion pipeline is:

```text
source artifact
    -> source preservation / Document Workspace
    -> Structure Agent
    -> Structure Auditor
    -> Extraction Agent
    -> Extraction Auditor
    -> Corpus API commit
```

OpenAI Agents SDK is the default runtime for the agent stages. JurisNexo application/worker code owns mandatory stage order, state transitions, provenance, evidence, and commit gates.

### Parallel breadth track

Phase 1 must not interpret "one artifact correct" as "discover only one artifact." In parallel, JurisNexo should inventory approved official SCJ source surfaces and record what is actually discoverable and downloadable.

Breadth work may register source documents/artifacts, checksums, source observations, reliable metadata, page-preserved text/OCR and cheap search representations without requiring deep issue/holding/treatment extraction.

The coverage manifest should distinguish at least:

```text
source claims
discovered records
downloadable artifacts
acquired artifacts
segmented decisions
canonical decisions
searchable decisions
deeply normalized decisions
known gaps
last reconciliation
```

Deliverables:

- official-source inventory and reconciliation baseline;
- artifact registration from existing Storage and official sources;
- cryptographic content hashing;
- immutable artifact provenance;
- Document Workspace with page/text/image capabilities;
- text extraction with page boundaries;
- extraction-quality assessment;
- OCR/image fallback where required;
- Structure Agent baseline;
- Structure Auditor baseline;
- decision-boundary detection with typed evidence;
- Extraction Agent for bounded full-decision reconstruction;
- Extraction Auditor for source/evidence verification;
- normalized/canonical case identity;
- artifact-page-to-case linkage;
- baseline citation extraction;
- Corpus API approved-commit path;
- baseline quality checks;
- ingestion idempotency;
- exact-content duplicate detection;
- layered structure/extraction/audit benchmarks.

Manual validation must inspect a representative sample of segmented and extracted decisions rather than trusting parser or agent output automatically.

Exit condition:

The selected compilation can be re-ingested without duplicate logical records; individual decisions are separated with acceptable benchmarked accuracy; extracted content is traceable to original source pages; mandatory structure/extraction audits cannot be bypassed; uncertain boundaries/identities remain explicit; duplicate source artifacts do not become duplicate canonical cases; and official-source coverage can be measured without claiming completeness that has not been observed.

Neither raw volume nor complete deep normalization of the discovered corpus is a Phase 1 exit condition.

## 4. Phase 2 — searchable corpus and high-signal intelligence seed

Goal: establish a strong, measurable retrieval baseline while expanding cheap trustworthy breadth and concentrating expensive semantic work on high-signal decisions.

Agent-assisted ingestion is already present in Phase 1. “Before complex agents” here means before broad multi-agent legal research orchestration, not before any LLM is used.

### Depth track

Deep normalization starts with the official SCJ `principales-sentencias` collection, using the validated early-2025 artifact as the first fixture and then expanding across the collection. Membership in Principales is an editorial priority signal, not a statement of precedential authority.

Recent 2024/2023 compilations remain useful early regression and retrieval fixtures, but they are not an artificial ceiling on corpus acquisition.

### Breadth track

In parallel, broader SCJ material should become cheaply discoverable/searchable as acquisition reliability permits. Its purpose includes:

- canonical identity resolution;
- exact/reference search;
- adverse-authority discovery;
- backward and forward citation traversal;
- coverage measurement;
- candidate promotion into deep normalization.

A broad record may therefore be useful before issues, holdings, factual propositions or contextual treatment have been deeply normalized.

Deliverables:

- exact decision/reference search;
- metadata filters;
- PostgreSQL full-text lexical search;
- semantic retrieval where text quality justifies it;
- RRF fusion baseline;
- reranker experiment;
- stable Search/Corpus API;
- corpus browser for internal testing;
- versioned retrieval profiles;
- initial 10-20 question manually reviewed legal benchmark;
- coverage-manifest reporting;
- source/editorial membership signals without intrinsic `is_principal` case truth.

Evaluation:

- Recall@K;
- nDCG@K;
- Critical Miss Rate;
- adverse-authority recall where applicable;
- evidence-page correctness;
- search latency;
- common failure analysis;
- discovered/acquired/searchable/deep-normalized coverage counts.

Compare at minimum:

```text
lexical only
semantic only
lexical + semantic + RRF
lexical + semantic + RRF + reranker
```

Exit condition:

Known relevant decisions for the seed benchmark are discoverable with acceptable recall, retrieval regressions can be measured, retrieved evidence maps back to exact source pages, and broad searchable coverage can grow without forcing deep semantic analysis of every document.

## 5. Phase 3 — citation graph and case reader

Goal: move from isolated search results toward evidence-backed jurisprudential navigation.

After reliable segmentation and canonical identity, citation extraction/resolution is a high-leverage corpus capability because it drives both research and selective normalization.

Deliverables:

- raw citation preservation with exact provenance;
- conservative citation resolution;
- `get_citations`;
- `get_citing_cases`;
- backward/forward citation traversal;
- promotion signals for important cited/citing authorities;
- within-case search;
- bounded Case Analyst agent;
- structured evidence records;
- exact page provenance;
- role-aware case structure where benchmarked useful;
- selective treatment classification only where valuable and adequately evidenced.

Exit condition:

Given a known case, JurisNexo can extract a relevant holding/reasoning segment, show where it appears in the original source, traverse important resolved citations, and preserve ambiguity instead of inventing citation or treatment certainty.

## 6. Phase 4 — research agent V0

Goal: demonstrate iterative research rather than one-shot RAG.

OpenAI Agents SDK is the default runtime. The root agent consumes stable Corpus API tools; it does not receive direct production database access.

Root agent tools:

- `search_cases`;
- `get_case`;
- `search_within_case`;
- `get_citations`;
- `get_citing_cases`;
- bounded Case Analyst as tool/specialist;
- deterministic aggregation tools;
- `verify_claim`.

Dynamic handoffs/agents-as-tools may be used for bounded specialists such as citation tracing, later-treatment review, or adverse-authority research. Mandatory research completion/verification requirements remain application/domain contracts rather than optional handoff behavior.

A general-purpose Python sandbox is not required for the first agent version if bounded deterministic tools cover the needed operations.

Required behavior:

- decompose question, including KELLER/LegalSearchLM-style multi-query strategies when benchmarked useful;
- run several retrieval strategies;
- review candidate cases;
- perform adverse search;
- follow important citations;
- check later treatment when possible;
- build structured evidence;
- distinguish searched corpus from unknown/unavailable material;
- stop against the completion contract.

Exit condition:

The system can complete end-to-end research on a narrow class of questions and produce reproducible evidence records without converting corpus gaps into false claims that contrary authority does not exist.

## 7. Phase 5 — evidence auditor and report

Goal: make outputs professionally inspectable.

Deliverables:

- independent claim/evidence verifier;
- report generator using only accepted evidence;
- supporting authority section;
- adverse authority section;
- material distinctions section;
- limitations/confidence section;
- searched-corpus/coverage disclosure;
- source links/page references;
- HTML report;
- optional PDF export after HTML is stable.

Exit condition:

A legal reviewer can move from every material report claim to its source with minimal friction and can understand material corpus/freshness limitations of the research run.

## 8. Phase 6 — multi-tenant QuisqueyaTech demo

Goal: expose the system to real users safely.

Delivery surface:

- QuisqueyaTech-hosted web app;
- JurisNexo branded experience;
- authenticated users;
- organization workspaces.

Deliverables:

- accounts;
- organizations;
- tenant authorization;
- free quota/credits;
- research job history;
- feedback capture;
- analytics;
- rate limits;
- private upload isolation if uploads are enabled.

Exit condition:

Multiple independent organizations can use the system without data leakage and usage can be measured accurately.

## 9. Phase 7 — private pilot

Goal: validate professional value.

Recommended pilot:

- 5–15 lawyers initially;
- real recently researched questions;
- structured post-report review;
- compare against known authorities and manual work.

Measure:

- Critical Miss Rate;
- adverse-authority recall;
- citation correctness;
- time saved;
- amount of additional research required;
- report usefulness;
- repeated usage;
- cost/job;
- corpus failures exposed by real research.

High-value failures should become durable regression cases and may promote source material for deeper normalization.

Exit condition:

There is evidence that the product materially reduces research work for at least one repeatable use case.

## 10. Phase 8 — controlled public demo

Only proceed if the private pilot is promising.

Deliverables may include:

- self-service signup;
- free monthly quota;
- standard versus deep research;
- queue/cost controls;
- improved onboarding;
- clear corpus-coverage disclosures;
- user feedback loop.

Exit condition:

We can observe real acquisition, activation, repeated use, and upgrade intent outside the initial personal network.

## 11. Phase 9 — paid validation

Do not build a broad billing catalog prematurely.

Test one or two simple hypotheses such as:

- paid deep-research credits;
- paid monthly research allowance;
- organization/team plan;
- paid API/integration pilot for one firm.

Goal:

Validate willingness to pay and unit economics.

## 12. Phase 10 — architecture upgrades driven by evidence

Potential upgrades, only after identifying bottlenecks:

### Retrieval quality bottleneck

Consider:

- stronger embeddings;
- ColBERT/multi-vector retrieval;
- SPLADE;
- learned reranking;
- dedicated BM25/search engine;
- domain fine-tuning.

### Query decomposition bottleneck

Consider deeper KELLER/LegalSearchLM-style decomposition only if simpler multiple-query prompting fails to recover critical/adverse authorities reliably.

### Legal-comparison bottleneck

Consider:

- Legal Elements;
- HYPO/CATO-style factor/dimension modeling;
- CaseGNN-like structural representations.

### Precedent-network bottleneck

Consider:

- proposition-level graph;
- CaseLink-like graph learning/ranking;
- graph database if relational traversal becomes painful;
- temporal treatment model.

### Corpus-wide synthesis bottleneck

Consider:

- GraphRAG/LegalGraphRAG/DRIFT-like global analysis;
- hierarchical summaries;
- dedicated doctrine/community indexes.

### Large-document processing bottleneck

Consider:

- RAPTOR-style hierarchy for within-case navigation;
- DocETL-style pipelines;
- LOTUS-style semantic operators;
- improved hierarchical document navigation.

### Workflow-durability bottleneck

If queue-based execution becomes difficult to reason about because of retries, branching, cancellation, fan-out, or long-lived research jobs, evaluate a durable workflow engine such as Temporal or Hatchet against the existing worker abstraction. OpenAI Agents SDK does not replace this durable workflow concern.

### Agent-runtime bottleneck

The selected runtime remains replaceable. Consider alternatives only when benchmarks/operations show a concrete limitation in quality, provider compatibility, tracing, portability, or maintainability.

## 13. Explicit non-goals before validation

Do not prioritize:

- deeply normalizing every acquired historical decision merely because it exists;
- treating document count as a product-quality metric;
- claiming national or institutional completeness before it is measured;
- autonomous legal drafting;
- outcome prediction;
- CRM/practice management;
- deep semantic integration of every Dominican court at once;
- custom model training without labels;
- elaborate graph infrastructure without proven need;
- mobile apps;
- international expansion;
- building another general-purpose agent harness inside JurisNexo.

Broad, cheap official-source inventory/acquisition is not a non-goal: it is useful when it improves provenance, coverage measurement, canonical resolution, retrieval and citation traversal without forcing expensive semantic enrichment.

## 14. First build slice

The smallest credible deep vertical slice remains:

```text
SCJ Jan-Apr 2025 compilation
        -> immutable artifact + checksum
        -> Document Workspace
        -> Structure Agent
        -> Structure Auditor
        -> bounded full-decision Extraction Agent
        -> Extraction Auditor
        -> canonical case commit through Corpus API
        -> searchable passages
        -> lexical + semantic retrieval baseline
        -> one benchmark legal question
        -> retrieve candidate cases
        -> bounded analysis of selected cases
        -> adverse search when applicable
        -> verify evidence against source pages
        -> generate one auditable report
```

In parallel, source discovery/reconciliation may cover substantially more material. That breadth track must not delay proving this deep slice, and the deep slice must not artificially prevent cheap breadth work.

The February 1980 historical bulletin remains an important adversarial/regression fixture for messy structure and discrepancy handling, but it must not become the architecture or the only ingestion benchmark.

## 15. Definition of MVP done

The MVP is not done when the UI looks polished, when many PDFs have been embedded, when an agent framework is integrated, or when a chatbot can quote a chunk.

It is done when:

- multiple organizations can use it;
- a real question can complete end to end;
- primary sources are preserved;
- compilations become correctly segmented canonical decisions;
- extracted decisions survive independent audit;
- supporting and adverse research occur;
- important report claims are verified;
- sources are auditable by page/evidence ID;
- searched-corpus boundaries and known gaps can be disclosed;
- quotas/costs are controlled;
- private data is tenant isolated;
- benchmark and product metrics are captured;
- at least a small pilot can evaluate real time saved.

## 16. Corpus expansion principle

Do not confuse **validation order** with **corpus acquisition order**.

For deep semantic processing, the order remains:

```text
one artifact correct
    -> one high-signal set measurable
    -> one research workflow trustworthy
    -> selectively deepen what evidence says matters
```

For cheap breadth, the parallel order is:

```text
official-source discovery
    -> immutable acquisition/provenance
    -> measurable coverage
    -> page-preserved searchable text
    -> citation/canonical-resolution support
```

The governing rule is therefore:

> validate depth narrowly, expand trustworthy breadth cheaply, and spend expensive semantic work selectively.

If one compilation cannot be transformed reliably into canonical, page-traceable legal evidence, processing many compilations deeply only creates a larger unreliable intelligence corpus. That does not justify ignoring inexpensive official-source discovery, acquisition, provenance and searchability that can improve coverage and future research.