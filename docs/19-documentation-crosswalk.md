# JurisNexo — Documentation Crosswalk for Agent Runtime Change

## Purpose

This crosswalk explains which documents are authoritative after the agent-runtime architecture change and prevents older design language from being read as a requirement to preserve the custom harness or superseded pre-ingestion compatibility surfaces.

## Current interpretation

The following existing documents remain authoritative for their domain contracts:

- `00-product-vision-and-mvp.md` — product/MVP goals;
- `01-system-architecture.md` — platform separation, Corpus API/search, PostgreSQL, workers, ingestion vs research;
- `02-legal-corpus-and-data-model.md` — corpus/data semantics, refined successively by `28-legal-reality-v2.md`, `33-extensible-judicial-semantics-and-disposition-targets.md`, and the current `34-adversarial-legal-reality-v3.md`;
- `03-research-agent-and-report-contract.md` — research lifecycle, specialist roles, auditor, evidence/report requirements;
- `04-validation-metrics-and-market-test.md` — product/market validation;
- `05-security-privacy-and-trust.md` — security/privacy/trust;
- `06-mvp-roadmap.md` — implementation milestones, now explicitly aligned with agent-assisted ingestion and SDK migration;
- `07-technical-rationale-and-open-decisions.md` — research-method rationale and open questions, superseded only where it assumes a bespoke agent runtime;
- `08-source-acquisition-coverage-and-canonical-identity.md` — source identity/acquisition;
- `09-tenancy-authentication-and-access-control.md` — authorization/tenancy;
- `10-job-state-machines-and-reproducibility.md` — durable job semantics/reproducibility, including the mandatory Structure/Audit/Extraction/Audit gates;
- `11-benchmark-annotation-and-evaluation-protocol.md` — benchmark discipline;
- `12-mvp-user-workflow-and-api-contract.md` — product-facing API/workflow.

The following documents define the current runtime/implementation direction and override conflicting assumptions about building a custom agent harness or about the current persisted legal model:

- `13-agent-runtime-and-multi-agent-orchestration.md` — canonical runtime/orchestration design;
- `14-agent-runtime-decision-record.md` — explicit ADR selecting OpenAI Agents SDK;
- `15-ingestion-agent-pipeline.md` — Structure -> Audit -> Extraction -> Audit pipeline;
- `16-corpus-api-agent-contract.md` — stable API boundary for agents;
- `17-agent-methodology-and-benchmark-map.md` — complete mapping of referenced research methodologies to measurable layers;
- `18-migration-plan-custom-harness-to-agents-sdk.md` — migration and retirement criteria;
- `20-agents-sdk-provider-and-guardrail-compatibility.md` — provider capability, structured-output, multimodal, handoff, guardrail, tracing, and upgrade constraints;
- `21-implementation-governance-and-agent-execution.md` — canonical implementation sequencing, workstream separation, parity requirements, and definition-of-done rules for implementation agents;
- `22-architecture-fitness-functions.md` — executable architecture-governance methodology and rules for creating/evolving structural fitness functions;
- `28-legal-reality-v2.md` — V2 pre-ingestion refinement for legal identities and cardinalities, including N:N proposition subjects/classification, contextual norm claims, judicial stances, shared legal entities, procedural claims, and decision state/event separation;
- `33-extensible-judicial-semantics-and-disposition-targets.md` — V2/V3-transition refinement introducing extensible opinion/stance/authority concepts and first-class typed judicial-disposition targets;
- `34-adversarial-legal-reality-v3.md` — **current canonical pre-ingestion refinement for persisted legal reality**, including explicit proceeding and cross-instance claim graphs, canonical-only legal semantics, disposition action identity, removal of compatibility aliases/mirrors, nullable unclassified adjudicative-act type, and the LAW-OWNED versus SYSTEM-OWNED vocabulary boundary.

For persisted legal/corpus semantics, read the refinements in order: `02` -> `28` -> `31`/`33` -> `34`. The newest document controls only the contracts it explicitly refines. In particular, compatibility language in `28`, `31`, or `33` is historical migration context when `34` explicitly removes that surface at the canonical migration head. Provenance, source preservation, primary-vs-interpretive epistemic boundaries, scope integrity, and bitemporal requirements remain mandatory unless `34` explicitly changes their representation.

`docs/testing/current-guarantees.toml` is the normative semantic guarantee inventory used by architecture/testing governance. It names durable guarantees and required evidence classes; it intentionally does not freeze exact test filenames.

## Operational agent instructions and reusable prompts

`AGENTS.md` is the repository-wide operational map for coding agents. It summarizes branch/CI discipline, what to read first, non-negotiable boundaries, benchmark/evidence rules, architecture-fitness policy, and validation expectations. `backend/AGENTS.md` adds the operational LAW-OWNED versus SYSTEM-OWNED gate for persisted legal categories. These files point back to the canonical docs instead of duplicating architecture rationale.

Reusable task prompts live under `prompts/`:

- `prompts/repository-conformance-audit.md` — read-only audit prompt for measuring current code against accepted docs;
- `prompts/implement-documented-architecture.md` — staged implementation prompt that begins from the audit and advances through independently testable/benchmarkable workstreams.

Prompts are execution aids, not architecture authority. If a prompt conflicts with accepted docs, the docs win and the prompt must be corrected.

## Conflict resolution rule

If an older document describes a custom implementation detail for generic agent runtime behavior and that detail conflicts with documents 13–22, the newer runtime/implementation documents take precedence.

For persisted legal reality, `34-adversarial-legal-reality-v3.md` is the latest refinement and takes precedence over conflicting compatibility-era statements in `28-legal-reality-v2.md`, `31-comprehensive-legal-semantics.md`, and `33-extensible-judicial-semantics-and-disposition-targets.md` for the contracts V3 explicitly changes. This includes:

- procedural ancestry living in `proceeding_relations`, not controversy-family membership;
- cross-instance claim lineage living in `claim_relations`;
- canonical-only concept/relation persistence without scalar or text mirrors removed by revision `0039`;
- `judicial_decisions.act_type_concept_id = NULL` as the intentional representation of an unclassified adjudicative-act form, with no fabricated default;
- dispositive clause -> `judicial_disposition_actions` -> `disposition_targets`, with the action owning the legal effect;
- removal of compatibility aliases such as `corpus.cases`, `precedential_authority_assertions`, `claim_effect_concepts`, and `disposition_claim_effects` from the canonical head;
- law-owned legal vocabularies being extensible data referenced by FK rather than closed DDL enums.

Accordingly, older statements saying that those specific compatibility columns, views, defaults, or synchronization triggers "remain" describe an earlier migration stage and must not be used as a reason to recreate them in the current schema.

This precedence does **not** relax older requirements concerning:

- provenance;
- source preservation;
- evidence verification;
- tenancy/security;
- benchmark discipline;
- research completion;
- adverse-authority search;
- database integrity;
- reproducibility;
- market validation.

Those remain mandatory unless explicitly changed by a future normative refinement or ADR.

## Architecture/testing interpretation rule

`docs/22-architecture-fitness-functions.md` defines when a documented architecture rule should become a deterministic fitness function. `docs/testing/current-guarantees.toml` defines the durable semantic guarantees and the evidence classes each one requires.

Architecture tests are blocking structural evidence, not substitutes for PostgreSQL/security/concurrency tests or semantic legal benchmarks. A fitness test should protect a stable risk/boundary rather than freeze incidental repository shape.

When architecture intentionally changes, update the current normative document, guarantee inventory when semantics change, and executable fitness/invariant evidence in one coherent change. Do not mechanically weaken a test or widen an allowlist only to make CI green.

## Research-method interpretation rule

`docs/07-technical-rationale-and-open-decisions.md` remains the rationale/source list for the research lines influencing JurisNexo. `docs/17-agent-methodology-and-benchmark-map.md` is the implementation/evaluation map explaining where each methodology may be adapted and what evidence must justify adopting its complexity.

A paper/reference appearing in `docs/07` is not automatically a production requirement. It becomes a candidate technique with a measurable hypothesis.

## Provider/runtime interpretation rule

"OpenAI Agents SDK" identifies the default runtime, not a guarantee that every model provider supports the same feature set.

Provider/model eligibility is capability-based and must follow `docs/20-agents-sdk-provider-and-guardrail-compatibility.md`. A provider that cannot satisfy a role's structured-output, tool, multimodal, usage, or other required capability must not be treated as interchangeable merely because an adapter can address it.

## Architectural shorthand

The current intended architecture is:

```text
Agent runtime: OpenAI Agents SDK
Model provider: capability + benchmark + configuration driven
Mandatory business stages: JurisNexo application orchestration
Domain access: Document Workspace + Corpus API
System of record: PostgreSQL + object storage
Trust layer: provenance + typed evidence + independent audit
Research method: iterative root agent + bounded specialists + claim verification
Evaluation: layered frozen benchmarks + real-user market validation
Implementation mode: small attributable workstreams with exact-head CI and semantic benchmark evidence
Architecture governance: normative guarantee inventory + blocking fitness functions + stronger evidence by risk class
Legal reality: explicit identity/cardinality relations that preserve multi-subject, multi-proceeding, cross-instance claims, scoped judicial stance, canonical disposition actions/targets, extensible legal vocabularies and bitemporal contextual truth
```
