# JurisNexo — Documentation Crosswalk for Agent Runtime Change

## Purpose

This crosswalk explains which documents are authoritative after the agent-runtime architecture change and prevents older design language from being read as a requirement to preserve the custom harness.

## Current interpretation

The following existing documents remain authoritative for their domain contracts:

- `00-product-vision-and-mvp.md` — product/MVP goals;
- `01-system-architecture.md` — platform separation, Corpus API/search, PostgreSQL, workers, ingestion vs research;
- `02-legal-corpus-and-data-model.md` — corpus/data semantics;
- `03-research-agent-and-report-contract.md` — research lifecycle, specialist roles, auditor, evidence/report requirements;
- `04-validation-metrics-and-market-test.md` — product/market validation;
- `05-security-privacy-and-trust.md` — security/privacy/trust;
- `06-mvp-roadmap.md` — implementation milestones, interpreted with the runtime migration plan;
- `07-technical-rationale-and-open-decisions.md` — prior rationale and open questions, superseded where it assumes a bespoke agent runtime;
- `08-source-acquisition-coverage-and-canonical-identity.md` — source identity/acquisition;
- `09-tenancy-authentication-and-access-control.md` — authorization/tenancy;
- `10-job-state-machines-and-reproducibility.md` — durable job semantics/reproducibility;
- `11-benchmark-annotation-and-evaluation-protocol.md` — benchmark discipline;
- `12-mvp-user-workflow-and-api-contract.md` — product-facing API/workflow.

The following documents define the new runtime direction and override conflicting assumptions about building a custom agent harness:

- `13-agent-runtime-and-multi-agent-orchestration.md` — canonical runtime/orchestration design;
- `14-agent-runtime-decision-record.md` — explicit ADR selecting OpenAI Agents SDK;
- `15-ingestion-agent-pipeline.md` — Structure -> Audit -> Extraction -> Audit pipeline;
- `16-corpus-api-agent-contract.md` — stable API boundary for agents;
- `17-agent-methodology-and-benchmark-map.md` — mapping of research methodologies to measurable layers;
- `18-migration-plan-custom-harness-to-agents-sdk.md` — migration and retirement criteria.

## Conflict resolution rule

If an older document describes a custom implementation detail for generic agent runtime behavior and that detail conflicts with documents 13–18, the newer runtime documents take precedence.

This precedence applies only to generic agent-runtime mechanics. It does **not** relax older requirements concerning:

- provenance;
- source preservation;
- evidence verification;
- tenancy/security;
- benchmark discipline;
- research completion;
- adverse-authority search;
- database integrity;
- reproducibility.

Those remain mandatory unless explicitly changed by a future ADR.

## Architectural shorthand

The current intended architecture is:

```text
Agent runtime: OpenAI Agents SDK
Model provider: benchmark/configuration driven
Mandatory business stages: JurisNexo application orchestration
Domain access: Document Workspace + Corpus API
System of record: PostgreSQL + object storage
Trust layer: provenance + typed evidence + independent audit
Research method: iterative root agent + bounded specialists + claim verification
Evaluation: layered frozen benchmarks + real-user market validation
```
