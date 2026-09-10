# JurisNexo — MVP Roadmap

## 1. Roadmap principle

The roadmap should optimize for evidence of product value, not architectural completeness.

The MVP should reach a point where real lawyers can submit real research questions, receive a verifiable report, and tell us whether it materially reduced their work.

## 2. Phase 0 — repository and contracts

Deliverables:

- product vision;
- architecture contract;
- corpus/data model;
- research-agent contract;
- evaluation plan;
- security/privacy baseline;
- explicit open decisions;
- technology stack and deployment contract;
- CI/testing contract;
- pilot-corpus contract.

Exit condition:

The team can explain what the MVP is, what it is not, how it will be built, what source material will be used first, and how success will be measured without relying on unwritten assumptions.

## 3. Phase 1 — corpus ingestion proof

Goal: prove that real Supreme Court source material can be turned into reliable searchable judicial records while preserving page-level provenance.

### Initial source

The first canonical ingestion fixture is the existing Supabase Storage artifact:

```text
Suprema Corte PDF/Principales_Decisiones_enero_abril_2025.pdf
```

This is a compilation and must not be modeled as one judicial case merely because it is one PDF.

The primary Phase 1 risk is therefore not bulk downloading. It is correctly transforming a compilation into individually identifiable, page-traceable decisions.

Deliverables:

- artifact registration from existing Storage;
- cryptographic content hashing;
- immutable artifact provenance;
- text extraction with page boundaries;
- extraction-quality assessment;
- OCR fallback where required;
- decision-boundary detection;
- normalized/canonical case identity;
- artifact-page-to-case linkage;
- baseline citation extraction;
- baseline quality checks;
- ingestion idempotency;
- exact-content duplicate detection.

Manual validation must inspect a representative sample of segmented decisions rather than trusting parser output automatically.

Exit condition:

The selected compilation can be re-ingested without duplicate logical records, individual decisions are separated with acceptable accuracy, every normalized passage can be traced to an original artifact page, uncertain boundaries/identities are represented explicitly, and duplicate source artifacts do not become duplicate canonical cases.

Volume is not the Phase 1 exit condition.

## 4. Phase 2 — searchable pilot corpus

Goal: establish a strong, measurable retrieval baseline before adding complex agents.

Initial corpus should remain deliberately constrained. After the early-2025 compilation is validated, expand first to recent 2024 and 2023 SCJ compilations rather than immediately processing the entire historical archive.

Recommended early expansion:

```text
2025 Jan-Apr
2024 Jan-Apr
2024 May-Aug
2024 Sep-Dec
2023 Jan-Apr
2023 May-Aug
2023 Sep-Dec
```

Deliverables:

- exact decision/reference search;
- metadata filters;
- PostgreSQL full-text lexical search;
- semantic retrieval;
- RRF fusion baseline;
- reranker experiment;
- stable Search API;
- corpus browser for internal testing;
- versioned retrieval profiles;
- initial 10-20 question manually reviewed legal benchmark.

Evaluation:

- Recall@K;
- nDCG@K;
- Critical Miss Rate;
- adverse-authority recall where applicable;
- evidence-page correctness;
- search latency;
- common failure analysis.

Compare at minimum:

```text
lexical only
semantic only
lexical + semantic + RRF
lexical + semantic + RRF + reranker
```

Exit condition:

Known relevant decisions for the seed benchmark are discoverable with acceptable recall, retrieval regressions can be measured, and the system can prove that retrieved evidence maps back to exact source pages.

## 5. Phase 3 — citation linking and case reader

Goal: move from search results to evidence-backed case understanding.

Deliverables:

- citation extraction;
- citation resolution;
- `get_citations`;
- `get_citing_cases`;
- within-case search;
- bounded case-analysis subagent;
- structured evidence records;
- exact page provenance.

Exit condition:

Given a known case, JurisNexo can extract a relevant holding/reasoning segment and show the user where it appears in the original source.

## 6. Phase 4 — research agent V0

Goal: demonstrate iterative research rather than one-shot RAG.

Root agent tools:

- `search_cases`;
- `get_case`;
- `search_within_case`;
- `get_citations`;
- `get_citing_cases`;
- `spawn_case_analysis`;
- deterministic aggregation tools;
- `verify_claim`.

A general-purpose Python sandbox is not required for the first agent version if bounded deterministic tools cover the needed operations.

Required behavior:

- decompose question;
- run several retrieval strategies;
- review candidate cases;
- perform adverse search;
- follow important citations;
- check later treatment when possible;
- build structured evidence;
- stop against the completion contract.

Exit condition:

The system can complete end-to-end research on a narrow class of questions and produce reproducible evidence records.

## 7. Phase 5 — evidence auditor and report

Goal: make outputs professionally inspectable.

Deliverables:

- claim/evidence verifier;
- report generator using only accepted evidence;
- supporting authority section;
- adverse authority section;
- material distinctions section;
- limitations/confidence section;
- source links/page references;
- HTML report;
- optional PDF export after HTML is stable.

Exit condition:

A legal reviewer can move from every material report claim to its source with minimal friction.

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
- cost/job.

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

### Legal-comparison bottleneck

Consider:

- Legal Elements;
- factor/dimension modeling;
- KELLER/LegalSearchLM-inspired query representation;
- CaseGNN-like structural representations.

### Precedent-network bottleneck

Consider:

- proposition-level graph;
- CaseLink-like graph learning;
- graph database if relational traversal becomes painful;
- temporal treatment model.

### Corpus-wide synthesis bottleneck

Consider:

- GraphRAG/DRIFT-like global analysis;
- hierarchical summaries;
- dedicated doctrine/community indexes.

### Large-document processing bottleneck

Consider:

- DocETL-style pipelines;
- LOTUS-style semantic operators;
- improved hierarchical document navigation.

### Workflow-durability bottleneck

If queue-based execution becomes difficult to reason about because of retries, branching, cancellation, fan-out, or long-lived research jobs, evaluate a durable workflow engine such as Temporal or Hatchet against the existing worker abstraction.

## 13. Explicit non-goals before validation

Do not prioritize:

- ingesting every currently available historical PDF merely because it exists;
- national full-corpus perfection;
- autonomous legal drafting;
- outcome prediction;
- CRM/practice management;
- every Dominican court at once;
- custom model training without labels;
- elaborate graph infrastructure without proven need;
- mobile apps;
- international expansion.

## 14. First build slice

The smallest credible vertical slice is now concrete:

```text
SCJ Jan-Apr 2025 compilation
        -> immutable artifact + checksum
        -> page-preserving extraction
        -> individual decision segmentation
        -> canonical case records
        -> searchable passages
        -> lexical + semantic retrieval baseline
        -> one benchmark legal question
        -> retrieve candidate cases
        -> bounded analysis of selected cases
        -> adverse search when applicable
        -> verify evidence against source pages
        -> generate one auditable report
```

This slice should be completed before aggressively expanding corpus volume or product features.

## 15. Definition of MVP done

The MVP is not done when the UI looks polished, when 34 PDFs have been embedded, or when a chatbot can quote a chunk.

It is done when:

- multiple organizations can use it;
- a real question can complete end to end;
- primary sources are preserved;
- compilations become correctly segmented canonical decisions;
- supporting and adverse research occur;
- important report claims are verified;
- sources are auditable by page;
- quotas/costs are controlled;
- private data is tenant isolated;
- benchmark and product metrics are captured;
- at least a small pilot can evaluate real time saved.

## 16. Corpus expansion principle

The existing Supreme Court collection is a head start, not a reason to optimize prematurely for volume.

The correct order is:

```text
one artifact correct
    -> one recent corpus measurable
    -> one research workflow trustworthy
    -> then expand coverage
```

If one compilation cannot be transformed reliably into canonical, page-traceable legal evidence, processing thirty-four compilations only creates a larger unreliable corpus.
