# JurisNexo — MVP System Architecture

## 1. Architectural goal

The MVP architecture should make one workflow reliable:

> ingest and normalize Dominican judicial decisions, make them efficiently searchable, allow a research agent to plan and execute iterative investigations over that corpus, verify the evidence it intends to cite, and produce an auditable report.

The architecture should remain simple enough for a prototype while preserving the boundaries required for later commercialization.

## 2. Core architectural principle

JurisNexo should not treat retrieval as the product architecture.

Retrieval is one capability exposed to a research runtime.

The research runtime may use deterministic search, semantic retrieval, citation traversal, Python analysis, and subagents. The model decides what to investigate; deterministic services decide how stored data is safely and reproducibly retrieved.

## 3. High-level architecture

```text
Public legal sources
        |
        v
Ingestion / normalization pipeline
        |
        +--> original artifacts
        +--> normalized cases
        +--> pages / passages
        +--> citations
        +--> search indexes
        |
        v
Shared public legal corpus
        |
        +------------------------+
                                 |
User / organization             |
        |                        |
        v                        v
Research request ------> Research runtime
                             |
                +------------+-------------+
                |            |             |
                v            v             v
             Search       Python       Subagents
             service      sandbox      / workers
                |            |             |
                +------------+-------------+
                             |
                             v
                     Evidence workspace
                             |
                             v
                         Auditor
                             |
                             v
                    Verified report
```

## 4. Recommended MVP components

### Web application

Responsibilities:

- authentication;
- organization/workspace selection;
- submit legal research request;
- optionally upload private supporting documents;
- display research status;
- display/export completed report;
- collect explicit user feedback.

The web layer should remain thin and should not contain research logic.

### Application API

Responsibilities:

- tenant-aware authorization;
- research job creation;
- usage/quota enforcement;
- report access;
- upload access;
- orchestration entry points;
- audit events.

### PostgreSQL

PostgreSQL should be the initial system of record.

Recommended initial capabilities:

- relational metadata;
- tenant data;
- normalized case records;
- page/passage records;
- explicit case citations;
- full-text search;
- `pgvector` if semantic retrieval is used;
- research jobs and evidence records.

A dedicated graph database should not be introduced until graph workloads justify it.

### Object storage

Store:

- original PDFs;
- page images when required;
- OCR artifacts;
- report exports;
- customer uploads.

Public source artifacts and tenant-private artifacts must be segregated logically and through access controls.

### Worker runtime

Long-running tasks should execute outside synchronous HTTP request lifetimes.

Workers may perform:

- OCR;
- normalization;
- embeddings;
- citation extraction;
- deep case analysis;
- agent research steps;
- report generation.

### Sandboxed Python environment

Python is the research agent's computational workspace, not the primary corpus store.

Approved operations may include:

- manipulate result sets;
- group by date/court/issue;
- build local citation graphs;
- calculate citation statistics;
- compare structured subagent outputs;
- deduplicate evidence;
- perform deterministic text matching;
- produce intermediate tables.

The sandbox must not have unrestricted production credentials, host filesystem access, or unrestricted network access.

## 5. Search service

The search service should expose a stable contract independent of the underlying ranking implementation.

Initial retrieval channels:

1. exact legal reference matching;
2. metadata filters;
3. PostgreSQL full-text lexical ranking as the initial lexical baseline;
4. semantic vector retrieval;
5. citation lookup/traversal.

PostgreSQL full-text ranking is not treated as native BM25. True BM25 or a dedicated lexical/hybrid engine remains an explicit benchmark-driven evolution option if the baseline shows a material retrieval deficiency.

Results can initially be fused using Reciprocal Rank Fusion or another transparent rank-fusion method.

A reranker should be evaluated early after the measurable baseline exists; it should be adopted only if it improves legal retrieval quality enough to justify its cost and latency.

Example conceptual API:

```text
search_cases(query, filters, limit)
get_case(case_id)
get_case_pages(case_id, pages)
search_within_case(case_id, query)
get_citations(case_id)
get_citing_cases(case_id)
resolve_legal_reference(reference)
```

The agent should not be allowed to query raw production tables arbitrarily when a stable service contract can provide the same operation.

## 6. Research runtime

The root research agent should have bounded tools rather than unrestricted infrastructure access.

Initial tool set:

```text
search_cases
get_case
search_within_case
get_citations
get_citing_cases
run_python
spawn_case_analysis
verify_claim
```

The root agent may:

- decompose a legal question;
- formulate multiple search strategies;
- assign candidate decisions to subagents;
- follow citation chains;
- search for later treatment;
- search for adverse authority;
- use Python to aggregate structured findings;
- decide which evidence gaps remain.

It may not publish a final report until the completion contract is satisfied or unresolved gaps are explicitly reported.

## 7. Subagent model

Subagents should receive bounded assignments and return structured outputs.

Example assignment:

> Review decision X only for the issue of defective notification and actual defenselessness. Identify material facts, relevant court reasoning, holding, outcome, cited authorities, exact supporting pages, and whether the decision supports, limits, distinguishes, or contradicts proposition Y.

Example output shape:

```json
{
  "case_id": "...",
  "relevant": true,
  "issues": [],
  "material_facts": [],
  "holding": [],
  "outcome": "...",
  "citations": [],
  "evidence": [],
  "relationship_to_query": "supporting",
  "uncertainties": []
}
```

Subagents should not independently write the final user report.

## 8. RLM influence

JurisNexo should adopt the useful ideas of Recursive Language Models without depending on a literal implementation where the entire corpus is loaded into a single Python variable.

Adopt:

- a root model capable of programmatic investigation;
- recursive/subagent delegation;
- external computational state;
- iterative exploration rather than one-shot context stuffing.

Do not adopt unnecessarily:

- repeated raw scans of the whole corpus;
- agent-written replacements for indexes or query services;
- unrestricted code execution;
- agent control over tenant authorization or provenance rules.

The normalized database and search API should perform cheap deterministic narrowing before expensive semantic analysis.

## 9. Ingestion versus research

These are separate systems.

### Ingestion path

```text
immutable source PDF/HTML
    -> deterministic extraction/OCR + document environment
    -> Structure Agent
    -> adversarial Structure Auditor
    -> bounded reinvestigation when required
    -> clean APPROVED structure
    -> DecisionWorkUnits + approved structural context
    -> bounded per-decision extraction
    -> extraction audit
    -> normalized searchable corpus
```

The Structure Agent performs document archaeology and routing rather than exhaustive legal extraction. Its job is to locate indexes or SUMARIO sections, understand printed/view pagination, identify recurring decision boundaries, record material anomalies, and produce one `DecisionWorkUnit` per indexed decision when possible.

### Durable structure findings

Document-level discoveries that can materially affect downstream work must be recorded as typed `structure_findings`, not only prose notes. Examples include:

- evidence that the stored artifact is an excerpt or incomplete scan of a larger printed volume;
- a printed-page to document-view pagination transform or offset;
- missing, duplicated, unresolved, or repeated scans;
- index destinations that disagree with observable source pagination;
- recurring decision-boundary patterns;
- OCR limitations that make a region unsafe for blind metadata extraction;
- source-identity or scan-composition facts relevant to later agents.

A structure finding carries a stable ID, type, statement, operational impact, confidence, typed source evidence when page-backed, machine-readable attributes, optional work-unit scope, and downstream instructions.

The Structure Auditor treats these findings as first-class claims. It may confirm, amend, reject, leave unresolved, or add a finding. It must not silently mutate the authoritative candidate. Any amendment, rejection, or newly added material finding produces `APPROVED_WITH_AMENDMENTS` (or a stricter state) and therefore requires a revised Structure Agent candidate followed by another audit. Only a clean `APPROVED` hypothesis may unlock extraction.

After clean approval, only material findings that are global or applicable to a specific `DecisionWorkUnit` are handed to downstream extraction agents. This `ApprovedStructureContext` is operational guidance, not primary legal evidence. For example, an approved pagination offset may tell an extractor how to navigate the source, but it cannot by itself prove a party name, date, holding, statute, or other legal fact. Those still require exact source evidence from the bounded decision.

### Recoverable agent errors

The ingestion runtime must distinguish expected investigation failures from actual software failures.

Expected request/domain conditions are model-visible and recoverable. Examples include:

- an unresolved printed page;
- a requested view page outside the current document view or bounded decision;
- an invalid/narrowable page range;
- an empty or oversized literal query;
- a tool response that exceeds the per-call evidence budget;
- final JSON/schema/provenance that the model can correct without repeating source investigation.

These conditions return bounded feedback such as `TOOL_REQUEST_REJECTED` or `FINALIZATION_REJECTED`. The agent must adapt its request or repair only the final payload. It should not repeat the same rejected operation.

Unexpected runtime exceptions, programming defects, corrupted state, invariant violations, and exhausted safety budgets remain fatal. JurisNexo must not use broad catch-and-continue behavior that hides genuine bugs.

Source-grounded SDK agents finalize through explicit repairable finalizer tools so deterministic schema and provenance validation occurs before a run is accepted. Architecture fitness tests enforce both rules: every SDK tool declares an explicit failure policy, and source-grounded ingestion agents must not bypass the repair loop with a native terminal `output_type` followed by post-run source validation.

### Research path

```text
user question
    -> issue decomposition
    -> candidate retrieval
    -> subagent analysis
    -> citation traversal
    -> adverse search
    -> Python aggregation
    -> evidence verification
    -> report
```

A query should not trigger expensive corpus-wide preprocessing that could have been done once during ingestion.

## 10. Progressive normalization

Do not require full semantic normalization for every decision before the MVP can operate.

### Level 0 — source preservation

- source URL;
- original PDF;
- checksum;
- acquisition time.

### Level 1 — searchable

- normalized text;
- page boundaries;
- court;
- date;
- decision identifier;
- source provenance;
- full-text index;
- optional embedding.

### Level 2 — structurally enriched

- chamber;
- matter;
- procedural type;
- cited laws;
- explicit cited cases;
- dispositive/outcome extraction where reliable.

### Level 3 — deep legal normalization

- legal issues;
- material facts;
- holdings;
- legal elements/factors;
- citation treatment;
- proposition-level relationships.

Deep normalization can be lazy and persisted when research jobs encounter important cases.

## 11. Caching and reusable knowledge

Research should create reusable verified artifacts where appropriate.

Possible reusable data:

- resolved citation links;
- verified holdings with provenance;
- normalized legal issues;
- candidate precedent relationships;
- court/chamber metadata corrections.

Interpretive knowledge must preserve:

- evidence location;
- extraction model/version;
- confidence;
- verification state;
- timestamp.

Model-generated interpretation must never overwrite the primary source.

## 12. Multi-tenancy

Shared:

- public jurisprudence;
- public-source normalization;
- shared search indexes;
- globally verified public-source metadata.

Tenant scoped:

- research queries;
- uploaded documents;
- reports;
- annotations;
- saved research;
- usage and billing;
- organization-specific corpora.

Every tenant-scoped row should carry an `organization_id` or be reachable only through a tenant-owned aggregate with enforced database/application authorization.

## 13. What not to build in the MVP

Avoid until evidence justifies them:

- Neo4j or another dedicated graph database;
- complex distributed microservices;
- custom-trained retrieval models;
- full Dominican legal ontology;
- proposition graph covering the whole corpus;
- outcome prediction;
- autonomous pleading filing;
- broad practice-management features.

## 14. Evolution path

The architecture must leave room for:

- stronger multilingual embeddings;
- ColBERT/multi-vector retrieval;
- learned Dominican legal rerankers;
- Legal Elements extraction;
- proposition-level precedent graphs;
- authority and temporal treatment scoring;
- GraphRAG-like corpus-wide exploration;
- organization APIs and integrations.

These should be introduced only when benchmark data shows which bottleneck they solve.
