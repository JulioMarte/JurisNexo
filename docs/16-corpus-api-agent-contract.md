# JurisNexo — Corpus API and Agent Contract

## 1. Purpose

The Corpus API is the stable boundary between agent runtimes and JurisNexo's system of record.

Agents should interact with capabilities, not production tables.

This contract exists so that model providers, agent frameworks, retrieval engines, and downstream agent roles can evolve without changing the meaning of corpus data.

## 2. Ownership boundary

The Corpus API owns:

- authorization and tenancy checks;
- validation of identifiers and state transitions;
- source/artifact/case membership;
- persisted evidence and analysis records;
- search contracts;
- canonical and versioned retrieval;
- write permissions by agent role;
- audit events.

The agent runtime owns:

- deciding which allowed tool/capability to call;
- constructing bounded arguments;
- interpreting returned evidence;
- producing structured candidate findings.

## 3. Initial capability groups

### Documents

```text
documents.get(document_id)
documents.get_pages(document_id, page_ids)
documents.search(document_id, query)
documents.render_page(document_id, page_id)
documents.get_neighbors(document_id, page_id, radius)
```

### Cases

```text
cases.get(case_id)
cases.get_text(case_id)
cases.get_pages(case_id, page_range)
cases.search(query, filters, limit)
cases.search_within(case_id, query)
```

### Citations

```text
citations.get(case_id)
citations.resolve(reference)
citations.get_citing_cases(case_id)
citations.record_candidate(...)
```

### Evidence

```text
evidence.record(...)
evidence.get(...)
evidence.verify(...)
```

### Analyses

```text
analysis.save(...)
analysis.get(...)
analysis.list_for_case(case_id)
```

### Ingestion

```text
ingestion.get_job(job_id)
ingestion.record_stage_output(...)
ingestion.request_review(...)
ingestion.commit_approved_case(...)
```

Names are conceptual until API implementation freezes them. Semantics matter more than endpoint spelling.

## 4. Read/write separation

Most research agents should be read-heavy.

A Research Agent may read cases/evidence and create research-job-scoped observations, but it should not mutate canonical source records.

An ingestion worker may propose canonical case records only through an approved commit path after required audits.

No agent receives generic SQL or unrestricted database credentials.

## 5. Evidence-first responses

API responses used for legal reasoning should return stable evidence identifiers where practical.

Example:

```json
{
  "case_id": "case_...",
  "text": "...",
  "evidence": [
    {
      "evidence_id": "ev_...",
      "artifact_id": "artifact_...",
      "page": 17,
      "role": "court_reasoning"
    }
  ]
}
```

This lets later agents and auditors refer to durable evidence rather than copy ambiguous page numbers through multiple transformations.

## 6. Agent role permissions

Tools should be role-scoped.

Examples:

```text
Structure Agent
  read source workspace
  record candidate observations
  cannot commit canonical cases

Structure Auditor
  read source + hypothesis
  record review
  cannot modify source artifact

Extraction Agent
  read approved case range
  record candidate extraction

Extraction Auditor
  read extraction + source
  approve/reject fields

Research Agent
  search/read corpus
  create research-job evidence
  cannot mutate canonical source

Research Auditor
  read report claims + evidence
  verify/reject claims
```

## 7. FastAPI and Python service layer

The MVP should implement the contract first as application services and FastAPI endpoints where external/process boundaries require HTTP.

Internal workers may call the same service interfaces directly in-process when appropriate, provided authorization and validation semantics remain identical.

Do not introduce microservices merely to make every call HTTP.

## 8. MCP evolution

MCP is a possible later adapter over the Corpus API, not the source of truth.

If introduced, MCP tools should wrap the same capability contracts and authorization rules rather than implement a second corpus semantics layer.

Potential consumers include:

- JurisNexo's own agents;
- customer-authorized assistants;
- internal legal-analysis tools;
- integrations with other agent runtimes.

## 9. Versioning

Version contracts that affect reproducibility:

- evidence schema;
- case normalization schema;
- analysis output schema;
- search/ranking configuration when results need replayability;
- ingestion stage outputs.

Do not force long-lived persisted records to depend on ephemeral SDK-specific objects.

## 10. Security

The API must enforce:

- organization scope;
- public vs private corpus visibility;
- object ownership;
- role/tool permissions;
- upload isolation;
- audit events for material writes;
- rate/quota limits where applicable.

Agent-level guardrails are an additional control, never a substitute for these checks.

## 11. Product significance

The Corpus API is intentionally more stable than the agent runtime.

A future migration from OpenAI Agents SDK to another runtime should ideally require adapting tool bindings, not redesigning the legal data model or corpus semantics.

This boundary also creates a path for the corpus and verified analyses to become reusable product capabilities beyond the first research-agent UI.
