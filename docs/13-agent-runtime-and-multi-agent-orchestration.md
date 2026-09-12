# JurisNexo — Agent Runtime and Multi-Agent Orchestration

## 1. Decision

JurisNexo will use **OpenAI Agents SDK** as the default agent runtime for the MVP instead of continuing to expand a custom general-purpose agent harness.

This is an infrastructure decision, not a commitment to use only OpenAI models. The runtime should remain capable of using OpenAI models and supported external model providers when benchmark results, cost, latency, or capability justify them.

JurisNexo will continue to own the domain-specific parts that create product value:

- legal-document tools and document workspaces;
- source preservation and canonical identity;
- provenance and evidence records;
- ingestion state machines and business orchestration;
- Corpus API contracts;
- authorization and tenancy;
- benchmark datasets, metrics, and release gates;
- legal research completion and verification contracts.

The agent runtime is replaceable infrastructure. The corpus, evidence model, API contracts, orchestration semantics, and benchmarks are not.

## 2. Why this change

The historical-bulletin experiments showed that JurisNexo was beginning to reimplement generic agent-runtime concerns such as:

- model/tool loops;
- provider retries;
- structured-output handling;
- context and token-budget management;
- subagent delegation;
- tracing;
- multi-agent control flow.

These are not the core differentiators of the product. Continuing to build them internally would increase maintenance burden and make it harder to focus on the difficult domain problem: extracting, verifying, storing, and researching messy legal documents.

The legal corpus is expected to contain unreliable OCR, inconsistent printed pagination, duplicated scans, incorrect indices, continuations across pages, damaged metadata, and source-specific layouts. LLMs therefore need freedom to investigate ambiguity. Deterministic code should constrain access, provenance, persistence, authorization, and verifiability rather than prescribe every reasoning step.

## 3. Architectural boundary

The runtime/framework owns generic agent mechanics:

```text
OpenAI Agents SDK
    -> agent/tool loop
    -> structured outputs
    -> handoffs / agents-as-tools
    -> guardrail hooks
    -> sessions/runtime state where appropriate
    -> tracing
    -> model invocation plumbing
```

JurisNexo owns domain and product behavior:

```text
JurisNexo
    -> document/case APIs
    -> ingestion orchestration
    -> evidence/provenance ledger
    -> source identity
    -> authorization
    -> persistence
    -> legal research contracts
    -> evaluation and benchmarks
```

Do not move security, tenant isolation, source identity, or evidence truth into LLM guardrails.

## 4. Ingestion is an explicit pipeline, not an uncontrolled swarm

The ingestion path should remain a deterministic business workflow whose difficult interpretation steps are delegated to agents.

Initial target flow:

```text
source artifact
    -> source preservation / extraction workspace
    -> Structure Agent
    -> Structure Auditor
    -> approved structural hypothesis
    -> Extraction Agent
    -> Extraction Auditor
    -> Corpus API commit
    -> reusable enrichment jobs
```

The Python application/worker controls this sequence. Agents do not decide whether required validation stages can be skipped.

### 4.1 Structure Agent

Purpose:

- explore an unfamiliar or messy document;
- identify likely artifact type;
- detect indexes, tables of contents, repeated regions, decision boundaries, continuations, and anomalies;
- propose candidate case/decision segments;
- attach observed evidence to each structural claim;
- explicitly mark ambiguity rather than fabricate certainty.

It may use document tools such as:

```text
search_document
read_page
read_pages
read_printed_page
render_page_image
inspect_neighbor_pages
```

Its output is a **candidate structural hypothesis**, not a database truth.

### 4.2 Structure Auditor

Purpose:

- independently challenge the structural hypothesis;
- inspect the source rather than merely review the first agent's prose;
- focus on candidate boundaries, index-reference mismatches, duplicated scans, missing pages, continuations, OCR artifacts, and contradictory page evidence;
- approve, amend, reject, or request more investigation.

The auditor should be adversarial by design. Its objective is to find material mistakes, not agree with the proposer.

### 4.3 Extraction Agent

Runs only after the relevant structure has sufficient approval.

Purpose:

- reconstruct the full content of a bounded judicial decision;
- preserve page/source linkage;
- extract reliable metadata and structured legal content progressively;
- distinguish court reasoning, facts, party arguments, dispositive text, and citations where supported;
- leave unknown fields unresolved rather than infer unsupported values.

Do not require one giant one-shot schema for every semantic layer. Prefer progressive passes when that improves accuracy, cost, or auditability.

Suggested progression:

```text
Pass 1: faithful text reconstruction
Pass 2: internal decision structure
Pass 3: metadata/entities
Pass 4: citations/legal references
Pass 5: deeper legal normalization / Legal Elements where justified
```

### 4.4 Extraction Auditor

Purpose:

- verify that extracted fields and material semantic claims are supported by the actual source;
- detect omissions, role confusion, unsupported normalization, and boundary leakage from adjacent decisions;
- attach verification state and uncertainty to persisted outputs.

The auditor must not silently rewrite primary-source content.

## 5. Handoffs versus explicit orchestration

Use **explicit application orchestration** for mandatory product stages:

```text
Structure -> Audit -> Extraction -> Audit -> Persist
```

These stages are business invariants and should be visible in job state.

Use **handoffs or agents-as-tools** for dynamic specialist work where the current agent may reasonably decide that another capability is needed, for example:

- citation resolution;
- difficult OCR interpretation;
- bounded decision-location investigation;
- later-treatment research;
- adverse-authority research;
- specialized case analysis.

A handoff must not bypass authorization, evidence requirements, budget limits, or mandatory pipeline stages.

## 6. Guardrail model

JurisNexo uses two distinct classes of guardrails.

### 6.1 Agent-level guardrails

These may use SDK guardrail hooks, structured validation, or specialized verifier agents.

Examples:

- a claim must cite evidence it actually inspected;
- a confirmed extraction may not be based only on an index entry;
- party argument may not be represented as a court holding;
- unresolved conflicts must remain visible;
- a specialist tool may reject an unsafe or malformed request.

### 6.2 System invariants

These are never delegated to an LLM:

- tenant and organization authorization;
- object ownership;
- valid `document_id`, `case_id`, page identity, and artifact version;
- source checksum and canonical identity;
- database constraints and foreign keys;
- immutable primary-source preservation;
- evidence/page membership;
- allowed state transitions;
- quota and billing enforcement;
- production credential boundaries.

Implement these using application code, API validation, Pydantic schemas, database constraints, and authorization policies.

## 7. Corpus API is the stable agent boundary

Agents should not query production database tables directly.

JurisNexo will expose a stable service layer, initially through Python/FastAPI and potentially later through MCP or other integration protocols.

Conceptual contracts include:

```text
documents.get
documents.pages
documents.search
documents.render_page

cases.get
cases.get_text
cases.get_pages
cases.search
cases.search_within

citations.get
citations.resolve
citations.get_citing_cases

evidence.record
evidence.verify

analysis.save
analysis.get

ingestion.commit
```

The exact API surface should remain small and capability-oriented. Agents receive only the operations needed for their role.

This API is part of the long-lived product architecture. Agent runtimes and model providers may change without changing corpus semantics.

## 8. Evidence model

Evidence must distinguish between where a source claim was observed and where the underlying content was observed.

For example, an index entry may state that a decision begins on printed page 353 while inspection finds the actual decision elsewhere. These are separate evidence objects, not interchangeable page lists.

Preferred conceptual representation:

```json
{
  "claim": "candidate decision starts at printed page 353",
  "source_evidence": [
    {
      "artifact_id": "...",
      "view_page": 4,
      "role": "index_entry"
    }
  ],
  "observed_content_evidence": [
    {
      "artifact_id": "...",
      "printed_page": 353,
      "view_page": 176,
      "role": "inspected_destination"
    }
  ],
  "verification_status": "contradictory"
}
```

The primary source remains immutable. Model-generated interpretations are append-only observations/analyses with model/version, evidence, confidence/verification state, and timestamps.

## 9. Research-agent architecture

The research system should consume the normalized corpus through the Corpus API, not raw ingestion internals.

Initial logical roles remain:

- root Research Agent;
- Case Analyst;
- Citation Tracer;
- Adverse Researcher;
- Auditor / Claim Verifier.

The root agent can use specialists as bounded tools or hand off a tightly scoped task. Specialists return structured findings and evidence; they do not independently publish the final user report.

The final report consumes verified evidence records whenever practical instead of regenerating facts directly from raw search results.

## 10. Paper/research methodology mapping

JurisNexo will adapt research ideas per layer rather than implement an entire paper architecture wholesale.

### 10.1 Recursive Language Model influence

Use for research and difficult document exploration:

- root model with programmatic tools;
- iterative investigation;
- bounded recursive/subagent delegation;
- external computational state;
- specialist calls when local context becomes difficult.

Do not use RLM ideas to replace authorization, storage, query APIs, source identity, or provenance.

### 10.2 Generator-verifier / critic patterns

Use where independent checking has clear value:

```text
Structure Agent -> Structure Auditor
Extraction Agent -> Extraction Auditor
Report synthesis -> Claim/Evidence Auditor
```

The verifier should inspect evidence independently and should be rewarded for finding errors rather than agreeing.

### 10.3 Retrieval methodologies

Keep retrieval modular and benchmarked:

- exact/legal-reference retrieval;
- lexical retrieval;
- semantic retrieval;
- rank fusion such as RRF;
- reranking when benchmark gains justify cost;
- citation traversal.

Do not embed one retrieval strategy permanently into the agent runtime.

### 10.4 Legal Elements / structured legal analysis

Deep legal normalization should be a later enrichment layer, not a prerequisite for ingesting every document.

Store extracted legal elements only with supporting evidence and extraction/version metadata.

### 10.5 GraphRAG / graph exploration

Do not introduce a dedicated graph architecture merely because citations form a graph. PostgreSQL and explicit citation edges remain the MVP baseline. Introduce graph-specific infrastructure only when benchmarks show a concrete corpus-wide exploration bottleneck.

## 11. Model-provider strategy

Do not hard-code one model for every role.

Evaluate models by task class:

- structure discovery;
- OCR/visual interpretation;
- extraction;
- audit/verification;
- retrieval query formulation;
- deep legal analysis;
- report synthesis.

Cheap models may be used for high-volume stages when they satisfy benchmark thresholds. Stronger models may be reserved for ambiguous or high-value stages.

Provider/model choice should be configuration and benchmark driven.

## 12. Tracing, reproducibility, and privacy

Agent tracing should record factual execution metadata needed to reproduce and diagnose a run:

- agent and model/version;
- tools called;
- inputs/outputs subject to privacy policy;
- evidence identifiers;
- token/cost usage;
- state transitions;
- guardrail/audit outcomes;
- failures/retries.

Do not expose or depend on private model chain-of-thought. Product traces should show actions, decisions represented as structured outputs, and evidence.

SDK-native tracing is useful operationally, but JurisNexo must keep its own durable job/evidence records because framework traces are not the system of record.

## 13. Job state and failure semantics

Long-running ingestion/research stays outside synchronous HTTP request lifetimes.

Possible ingestion states should make required gates explicit, for example:

```text
SOURCE_ACQUIRED
STRUCTURE_DISCOVERY_RUNNING
STRUCTURE_REVIEW_REQUIRED
STRUCTURE_APPROVED
EXTRACTION_RUNNING
EXTRACTION_REVIEW_REQUIRED
EXTRACTION_APPROVED
PERSISTING
COMPLETED
FAILED
BUDGET_LIMIT_REACHED
SOURCE_QUALITY_BLOCKED
```

Agent/provider failures must be distinguishable from semantic validation failures and from deterministic system failures.

## 14. Benchmark strategy

Do not tune runtime behavior to a single historical PDF or leak frozen gold answers into prompts/tools.

Benchmarks should be layered:

1. document-structure discovery;
2. discrepancy/boundary resolution;
3. full decision extraction;
4. metadata/citation extraction;
5. evidence verification;
6. retrieval;
7. case analysis;
8. end-to-end legal research.

For each meaningful architectural change, compare against the current baseline with frozen inputs and independent gold where practical.

Track quality, not merely whether the workflow process exits successfully.

Relevant metrics include:

- boundary accuracy;
- text completeness/fidelity;
- field precision/recall/F1;
- citation correctness;
- evidence completeness;
- critical/adverse-authority recall;
- Critical Miss Rate;
- cost and latency;
- human-rated usefulness and additional research required.

## 15. Migration from the custom harness

Do not delete the current harness immediately.

Migration sequence:

1. preserve current historical benchmarks as a baseline;
2. implement one equivalent document-exploration agent using OpenAI Agents SDK;
3. expose existing `DocumentEnvironment` capabilities as SDK tools where still useful;
4. replace generic custom loop/provider orchestration only after comparative tests;
5. retain JurisNexo provenance, evidence, scorer, API, and job-state components;
6. delete superseded runtime code only after benchmark parity/improvement and CI coverage.

The migration must not silently weaken traceability or evidence requirements in exchange for easier agent development.

## 16. What not to build

Do not build, unless benchmark evidence later requires it:

- another generic agent framework inside JurisNexo;
- custom handoff protocols when the runtime already provides them;
- custom model loops merely to mirror SDK behavior;
- arbitrary context-size heuristics as the main reasoning architecture;
- unrestricted database access for agents;
- an autonomous agent swarm for deterministic ETL stages;
- a graph database before graph workload evidence exists;
- one giant schema that attempts to solve all legal normalization in one model call.

## 17. Commercialization principle

The component most likely to determine whether JurisNexo is valuable is not the agent framework.

The defensible product layer is the combination of:

- a trustworthy Dominican legal corpus;
- source/evidence provenance;
- reusable legal APIs;
- verified enrichments;
- domain-specific evaluation datasets;
- research workflows that reliably find supporting and adverse authority;
- measurable reduction in lawyer research time without unacceptable critical misses.

Framework sophistication is useful only when it improves those outcomes.
