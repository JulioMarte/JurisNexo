# JurisNexo — Documentation Crosswalk for Agent Runtime Change

## Purpose

This crosswalk explains which documents are authoritative after the agent-runtime architecture change and prevents older design language from being read as a requirement to preserve the custom harness, superseded pre-ingestion compatibility surfaces, or an obsolete pre-production repository shape.

## Current interpretation

The following existing documents remain authoritative for their domain contracts:

- `00-product-vision-and-mvp.md` — product/MVP goals;
- `01-system-architecture.md` — platform separation, Corpus API/search, PostgreSQL, workers, ingestion vs research;
- `02-legal-corpus-and-data-model.md` — corpus/data semantics, refined successively by `28-legal-reality-v2.md`, `33-extensible-judicial-semantics-and-disposition-targets.md`, `34-adversarial-legal-reality-v3.md`, and the current `35-legal-reality-v4.md`;
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
- `23-pre-production-evolution-and-adversarial-proof-policy.md` — normative current policy for deliberate pre-production architecture/test evolution: freeze evidence rather than accidental shape, preserve HARD guarantees, disposition old proof explicitly, and require adversarial/exact-head evidence for replacements.
- `28-legal-reality-v2.md` — V2 pre-ingestion refinement for legal identities and cardinalities, including N:N proposition subjects/classification, contextual norm claims, judicial stances, shared legal entities, procedural claims, and decision state/event separation;
- `33-extensible-judicial-semantics-and-disposition-targets.md` — V2/V3-transition refinement introducing extensible opinion/stance/authority concepts and the first action/target dispositive model;
- `34-adversarial-legal-reality-v3.md` — V3 refinement introducing explicit proceeding and cross-instance claim graphs, canonical-only legal semantics, disposition action identity, removal of compatibility aliases/mirrors, nullable unclassified adjudicative-act type, and the LAW-OWNED versus SYSTEM-OWNED vocabulary boundary;
- `35-legal-reality-v4.md` — **current canonical pre-ingestion refinement for persisted legal reality**, separating legal issues and factual propositions from legal propositions, replacing single typed disposition targets with typed action arguments, adding auditable entity-resolution history, and establishing the shared concept foundation for new cross-jurisdiction semantics.

For persisted legal/corpus semantics, read the refinements in order: `02` -> `28` -> `31`/`33` -> `34` -> `35`. The newest document controls only the contracts it explicitly refines. In particular, V3's proceeding graph, claim lineage, judicial stance, canonical-only semantics, bitemporal truth and open-vocabulary rules remain in force; V4 specifically supersedes V3's disposition target representation and the use of `legal_propositions` for issues/material facts/procedural facts.

The testing-governance layer is split deliberately:

- `docs/testing/current-guarantees.toml` — **normative** semantic guarantee inventory and required evidence classes;
- `docs/testing/repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL repository and evidence-governance policy;
- `docs/testing/evidence-authoring-guide.md` — normative falsifiable-proof authoring rules;
- `docs/testing/current-proof-map.toml` — **non-normative** map of representative current proof and explicit evidence gaps;
- `docs/testing/test-architecture-migration.md` — **non-normative** ledger of KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL proof migration decisions.

The guarantee inventory intentionally does not freeze exact test filenames. The proof map and migration ledger may evolve as equal-or-stronger proof moves between execution boundaries.

## Operational agent instructions and reusable prompts

`AGENTS.md` is the repository-wide operational map for coding agents. It summarizes branch/CI discipline, what to read first, non-negotiable boundaries, benchmark/evidence rules, architecture-fitness policy, and validation expectations. `backend/AGENTS.md` adds the operational LAW-OWNED versus SYSTEM-OWNED gate and V4 persisted-model rules. These files point back to the canonical docs instead of duplicating architecture rationale.

Nearer `AGENTS.md` files add path-specific execution rules. In particular, `backend/tests/AGENTS.md` owns test-authoring operations, while `docs/AGENTS.md` owns documentation maintenance discipline. Tool-specific `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, and `.github/instructions/*.instructions.md` files are adapters only.

Reusable task prompts live under `prompts/`:

- `prompts/repository-conformance-audit.md` — read-only audit prompt for measuring current code against accepted docs;
- `prompts/implement-documented-architecture.md` — staged implementation prompt that begins from the audit and advances through independently testable/benchmarkable workstreams.

Prompts are execution aids, not architecture authority. If a prompt conflicts with accepted docs, the docs win and the prompt must be corrected.

## Conflict resolution rule

If an older document describes a custom implementation detail for generic agent runtime behavior and that detail conflicts with documents 13–23, the newer runtime/implementation/evolution documents take precedence.

This precedence applies only to generic agent-runtime/implementation/repository-shape mechanics.

For persisted legal reality, `35-legal-reality-v4.md` is the latest refinement and takes precedence for contracts it explicitly changes. `34-adversarial-legal-reality-v3.md` remains authoritative for V3 contracts not modified by V4. At the canonical V4 migration head this includes:

- procedural ancestry living in `proceeding_relations`, not controversy-family membership;
- cross-instance claim lineage living in `claim_relations`;
- canonical-only concept/relation persistence without removed scalar/text mirrors or alias views;
- `judicial_decisions.act_type_concept_id = NULL` as the intentional representation of an unclassified adjudicative-act form, with no fabricated default;
- legal questions/issues living in `legal_issues`, not as `legal_propositions.proposition_type='issue'`;
- allegations/findings and other factual propositions living in `factual_propositions`, not as legal proposition material/procedural fact categories;
- dispositive clause -> `judicial_disposition_actions` -> `judicial_disposition_action_arguments`, with the action owning the legal effect and arguments carrying roles such as object, obligor, beneficiary, destination or amount;
- removal of V3 `disposition_targets` and `disposition_effect_concepts.target_type` after target data is migrated to `object` arguments;
- auditable `entity_identity_assertions` and bitemporal `entity_identity_resolutions` instead of destructive name-based merging;
- the shared `concept_schemes` / `legal_concepts` substrate being the default for **new** cross-domain legal vocabularies, without mechanically rewriting mature specialized registries;
- law-owned legal vocabularies remaining extensible data referenced by FK rather than closed DDL enums.

Accordingly, older statements saying that superseded compatibility columns, views, target tables, defaults, or synchronization triggers "remain" describe an earlier migration stage and must not be used as a reason to recreate them in the current schema.

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

Those remain mandatory unless explicitly changed by a future normative refinement, ADR, or accepted contract with equal-or-stronger protection.

## Pre-production evolution rule

JurisNexo currently follows:

```text
freeze the evidence, not the future
```

Historical benchmark/custom-harness/checkpoint artifacts may remain reproducible provenance without requiring current product head to preserve their incidental runtime, provider, prompt, test path, or repository shape.

When current architecture intentionally supersedes an old restriction, `23-pre-production-evolution-and-adversarial-proof-policy.md` requires reviewers to identify the old rule, why it is insufficient, the new contract, guarantee disposition, test disposition, adversarial proof, compatibility decision, and exact-head evidence.

This rule must not be used to weaken HARD source/provenance/security/authority/benchmark guarantees.

## Architecture/testing interpretation rule

`docs/22-architecture-fitness-functions.md` defines when a documented architecture rule should become a deterministic fitness function. `docs/testing/current-guarantees.toml` defines the durable semantic guarantees and the evidence classes each one requires.

Architecture tests are blocking structural evidence, not substitutes for PostgreSQL/security/concurrency tests or semantic legal benchmarks. A fitness test should protect a stable risk/boundary rather than freeze incidental repository shape.

`backend/tests/conftest.py` classifies `tests/architecture/**` as effective `fitness` evidence by ownership. `backend/scripts/ci/audit_test_architecture.py` inventories physical test scope and evidence metadata and detects historical/release proof contaminating the current architecture lane. The blocking architecture suite executes that audit.

When architecture intentionally changes, update the current normative document, guarantee inventory when semantics change, proof map when representative evidence changes, and executable fitness/invariant function in one coherent change. Do not mechanically weaken a test or widen an allowlist only to make CI green.

V4 adds `backend/tests/legal_model/` as executable PostgreSQL evidence for legal-domain semantics. These tests supplement rather than replace the existing integration/invariant suites.

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
Architecture governance: normative guarantees + blocking fitness + proof map + explicit evidence gaps
Evolution mode: freeze evidence, not accidental pre-production shape
Legal reality: controversy/proceeding/claim/decision graph + scoped judicial stance + first-class legal issues and factual propositions + disposition actions with typed arguments + auditable entity resolution + bitemporal contextual truth
```
