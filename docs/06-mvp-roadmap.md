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
- explicit open decisions.

Exit condition:

The team can explain what the MVP is, what it is not, and how success will be measured without relying on unwritten assumptions.

## 3. Phase 1 — corpus ingestion proof

Goal: prove that official legal sources can be turned into reliable searchable records.

Recommended scope:

- a small SCJ and/or TC sample;
- mix born-digital PDFs and scanned PDFs;
- retain page-level provenance.

Deliverables:

- source downloader/importer;
- artifact storage;
- text extraction;
- OCR fallback;
- normalized case identity;
- page records;
- baseline quality checks;
- ingestion idempotency.

Exit condition:

At least several hundred representative decisions can be ingested repeatedly without losing source/page provenance.

## 4. Phase 2 — searchable corpus

Goal: establish a strong, measurable retrieval baseline before adding complex agents.

Deliverables:

- exact decision/reference search;
- metadata filters;
- PostgreSQL full-text search;
- semantic retrieval if useful;
- result fusion;
- stable Search API;
- corpus browser for internal testing.

Evaluation:

- initial Recall@K;
- nDCG@K;
- search latency;
- common failure analysis.

Exit condition:

Known relevant decisions for a seed benchmark are discoverable with acceptable recall.

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
- `run_python`;
- `verify_claim`.

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

## 13. Explicit non-goals before validation

Do not prioritize:

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

The smallest credible vertical slice is:

```text
50–500 representative decisions
        -> ingest with page provenance
        -> searchable index
        -> submit one legal question
        -> retrieve candidates
        -> subagent reviews selected cases
        -> adverse search
        -> verify claims
        -> generate one auditable report
```

This slice should be completed before expanding corpus or features aggressively.

## 15. Definition of MVP done

The MVP is not done when the UI looks polished.

It is done when:

- multiple organizations can use it;
- a real question can complete end to end;
- primary sources are preserved;
- supporting and adverse research occur;
- important report claims are verified;
- sources are auditable by page;
- quotas/costs are controlled;
- private data is tenant isolated;
- benchmark and product metrics are captured;
- at least a small pilot can evaluate real time saved.
