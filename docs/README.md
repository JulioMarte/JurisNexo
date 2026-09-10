# JurisNexo Documentation

This directory defines the product and engineering contract for the JurisNexo MVP.

The documents are intentionally ordered from product intent to implementation, operational integrity, and validation.

## Documents

1. [`00-product-vision-and-mvp.md`](./00-product-vision-and-mvp.md) — product thesis, initial customer, first paid unit of value, QuisqueyaTech validation strategy, multi-tenant requirement, and MVP boundaries.
2. [`01-system-architecture.md`](./01-system-architecture.md) — MVP architecture, corpus/search services, research runtime, RLM influence, progressive normalization, and evolution path.
3. [`02-legal-corpus-and-data-model.md`](./02-legal-corpus-and-data-model.md) — source preservation, searchable case model, citations, holdings, legal issues, precedent relationships, provenance, OCR, and normalization levels.
4. [`03-research-agent-and-report-contract.md`](./03-research-agent-and-report-contract.md) — research lifecycle, subagents, adverse-authority search, completion criteria, Python workspace, evidence verification, and final report contract.
5. [`04-validation-metrics-and-market-test.md`](./04-validation-metrics-and-market-test.md) — legal retrieval metrics, Critical Miss Rate, human evaluation, time-saved measurement, pilot design, free demo, and go/no-go criteria.
6. [`05-security-privacy-and-trust.md`](./05-security-privacy-and-trust.md) — tenant isolation, private legal data, model-provider boundaries, prompt injection, Python sandbox, provenance, retention, and trust disclosures.
7. [`06-mvp-roadmap.md`](./06-mvp-roadmap.md) — evidence-driven implementation sequence from corpus ingestion through private pilot, controlled demo, and paid validation.
8. [`07-technical-rationale-and-open-decisions.md`](./07-technical-rationale-and-open-decisions.md) — why JurisNexo combines legal IR, case reasoning, citation analysis, RLM-style agents, DocETL/LOTUS ideas, and why complexity must be benchmark-driven.
9. [`08-source-acquisition-coverage-and-canonical-identity.md`](./08-source-acquisition-coverage-and-canonical-identity.md) — official-source registry, acquisition/versioning, duplicate resolution, canonical case identity, measurable corpus coverage, and freshness.
10. [`09-tenancy-authentication-and-access-control.md`](./09-tenancy-authentication-and-access-control.md) — organization/user model, roles, authorization invariants, worker execution scope, private/public evidence boundaries, and negative isolation tests.
11. [`10-job-state-machines-and-reproducibility.md`](./10-job-state-machines-and-reproducibility.md) — ingestion/research state machines, retries, idempotency, failure taxonomy, corpus snapshots, and reproducible report provenance.
12. [`11-benchmark-annotation-and-evaluation-protocol.md`](./11-benchmark-annotation-and-evaluation-protocol.md) — how real legal research tasks are annotated, critical/adverse authority labels, evidence judgments, locked test sets, regression gates, and failure analysis.
13. [`12-mvp-user-workflow-and-api-contract.md`](./12-mvp-user-workflow-and-api-contract.md) — exact report-first user journey, core API resources, progress events, report/evidence contracts, feedback, uploads, and demo quotas.

## Current MVP definition

JurisNexo is a multi-tenant experimental legal research product initially validated under QuisqueyaTech.

The first product is a **Precedent & Adverse Authority Report**. A user provides a legal question or fact pattern. JurisNexo investigates relevant Dominican jurisprudence, reviews supporting and adverse authorities, follows material citations, verifies important claims against primary sources, and returns an auditable report.

The MVP should begin with SCJ/TC jurisprudence and a deliberately constrained corpus/domain if necessary.

## Non-negotiable invariants

- Primary legal sources remain immutable and authoritative.
- Model-generated interpretation never silently becomes source truth.
- Public jurisprudence and tenant-private content are separate data classes.
- Every material report claim must be traceable to evidence.
- Adverse-authority search is part of deep research, not an optional feature.
- Multi-tenancy exists before paid plans.
- Authorization is enforced below the model/UI layer.
- The research agent uses retrieval; it is not merely a wrapper around one retrieval call.
- Deterministic operations should remain deterministic.
- Corpus coverage and freshness are measured and disclosed rather than assumed.
- Completed reports retain the source/evidence/configuration snapshot they were produced from.
- Added architectural complexity must improve measured outcomes.
- Product-market validation precedes broad platform expansion.

## Immediate implementation target

Build the smallest end-to-end slice that can prove the thesis:

```text
representative SCJ/TC decisions
    -> source registry + immutable acquisition
    -> canonical identity + normalized page-level corpus
    -> measurable coverage/freshness
    -> searchable retrieval baseline
    -> legal research request
    -> iterative agent research
    -> case subagent review
    -> adverse search + citation traversal
    -> evidence verification
    -> auditable report snapshot
    -> legal-user feedback
```

Only after this slice works should corpus breadth and sophisticated retrieval/graph techniques become the priority.

## Documentation completeness rule

An implementation decision is not considered settled merely because it appears in code. If it affects product scope, legal-source integrity, multi-tenant isolation, research completion, evidence semantics, evaluation, report reproducibility, or commercialization boundaries, it should be reflected in these documents or captured explicitly as an open decision.
