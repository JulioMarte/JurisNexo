# JurisNexo — agent operating map

These instructions apply repository-wide. A nearer `AGENTS.md` may add path-specific rules but must not contradict current repository policy.

`AGENTS.md` is an operational map, not the architecture manual. The repository documentation under `docs/` is the source of truth for product, data, agent, evidence, security, benchmark, migration, and executable architecture contracts.

## Reporting discipline — mandatory

When reporting work:

1. explain what changed in system/product terms;
2. state what was not changed;
3. distinguish implemented behavior from documented/intended behavior;
4. identify decisions made, assumptions, unresolved risks, and known pre-existing issues;
5. never report a check or benchmark as passing unless it actually ran against the intended commit/environment;
6. distinguish CI/process success from semantic benchmark success.

## Current repository mode

JurisNexo is an early-stage MVP/research system. The immediate objective is not architectural completeness; it is to build the smallest trustworthy legal-document and legal-research pipeline that can be benchmarked and tested with real lawyers.

The current architecture is undergoing a controlled migration away from a custom general-purpose agent harness toward **OpenAI Agents SDK** as the default MVP agent runtime.

The current custom harness is a temporary benchmark baseline and a source of reusable document-domain capabilities. Do not delete it merely because the new runtime has been selected. Retire generic runtime code only after the replacement demonstrates benchmark parity or improvement and preserves provenance/evidence guarantees.

## Current product/data direction — mandatory discovery

The current corpus/product strategy is **broad cheap discoverability + selective verified depth**. JurisNexo is building a Dominican jurisprudential intelligence layer, not merely a large PDF collection or a generic legal chatbot.

Read `docs/38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md` before proposing broad corpus, retrieval, citation, enrichment, research-agent, or legal-analytics work.

Current critical path:

```text
official source inventory
    -> canonical identity + exact provenance
    -> searchable corpus
    -> explicit citation extraction/resolution
    -> priority-driven deep normalization
    -> legal issues/propositions/treatments with evidence
    -> Precedent & Adverse Authority research
    -> lawyer corrections -> benchmark/regression corpus
```

SCJ `principales-sentencias` is the initial high-signal seed for semantic depth. Broader SCJ and later multi-court material should become searchable without requiring full semantic normalization first. Membership in an editorial collection is a scheduling/importance signal, never an automatic legal-authority score.

Do not propose mass deep normalization, a graph database, a custom legal model, or broad legal-analytics statistics merely because the schema can support them. Require measured source coverage and a demonstrated product/benchmark need.

## Branch workflow — mandatory

`main` is the canonical integration branch.

For normal feature, fix, refactor, benchmark, documentation, migration, or agent work:

1. resolve the latest `main`;
2. create a short-lived branch from that exact head;
3. use a descriptive prefix such as `feature/`, `fix/`, `hardening/`, `docs/`, or `chore/`;
4. keep one coherent change per PR where practical;
5. open the PR against `main`;
6. require exact-head CI before merge;
7. merge only the exact reviewed/green head SHA;
8. delete the merged branch;
9. create follow-up work from the new `main` head rather than reusing the branch.

Do not claim a stale CI run proves the current head. Do not merge a materially stale branch without reconciling it against current `main`.

See `CONTRIBUTING.md` for repository branch and merge policy.

## Start here

Read only the canonical material needed for the task, but resolve conflicts using the documentation crosswalk.

Recommended order:

1. `README.md` — product thesis and current architecture direction;
2. `docs/19-documentation-crosswalk.md` — authority/precedence between old and new documents;
3. `docs/38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md` — canonical corpus/product flywheel, SCJ Principales seed strategy, citation-first expansion, and current moat/priority rules;\n5. `docs/01-system-architecture.md` — platform boundaries;
4. `docs/13-agent-runtime-and-multi-agent-orchestration.md` — canonical agent-runtime/orchestration contract;\n6. `docs/15-ingestion-agent-pipeline.md` — Structure -> Audit -> Extraction -> Audit pipeline;\n7. `docs/16-corpus-api-agent-contract.md` — stable agent/data boundary;\n8. `docs/20-agents-sdk-provider-and-guardrail-compatibility.md` — provider/SDK capability constraints;\n9. `docs/21-implementation-governance-and-agent-execution.md` — implementation sequencing and migration discipline;\n10. `docs/22-architecture-fitness-functions.md` and `docs/testing/current-guarantees.toml` — executable architecture policy and normative guarantee inventory;\n11. `docs/02-legal-corpus-and-data-model.md` when changing persisted legal/corpus data;\n12. `docs/03-research-agent-and-report-contract.md` when changing legal research behavior;\n13. `docs/10-job-state-machines-and-reproducibility.md` when changing long-running jobs or durable execution;\n14. `docs/11-benchmark-annotation-and-evaluation-protocol.md` and `docs/17-agent-methodology-and-benchmark-map.md` when changing benchmarks, retrieval, agent behavior, or research methods;\n15. `docs/05-security-privacy-and-trust.md` and `docs/09-tenancy-authentication-and-access-control.md` for trust/tenant-sensitive changes;\n16. `docs/18-migration-plan-custom-harness-to-agents-sdk.md` for runtime migration work;\n17. `docs/27-database-bootstrap-and-multi-court-registry.md` for database bootstrap, PostgreSQL configuration, and ephemeral-CI database policy.

Do not treat historical benchmark behavior or the current implementation as authoritative when it conflicts with accepted current docs. Conversely, do not assume documented architecture has already been implemented: verify the code.

## Non-negotiable architecture

- Primary legal sources are authoritative; model interpretation is not.
- OpenAI Agents SDK is the default MVP agent runtime, not the legal system of record.
- Model/provider selection is capability- and benchmark-driven; providers are not assumed feature-equivalent.
- Mandatory ingestion stages remain explicit application/job orchestration: `Structure Agent -> Structure Auditor -> Extraction Agent -> Extraction Auditor -> Corpus API commit`.
- Handoffs/agents-as-tools are for bounded dynamic specialist work, not for bypassing mandatory pipeline gates.
- Agents do not receive unrestricted SQL or production database credentials.
- Corpus/document access goes through stable capabilities/services.
- PostgreSQL plus object storage remains the system of record for durable corpus/application state.
- SDK tracing is operational evidence, not durable legal/evidence truth.
- Source identity, checksum, provenance, authorization, tenant isolation, evidence membership, state transitions, and database integrity are deterministic system responsibilities.
- LLMs handle semantic ambiguity: damaged OCR, document structure hypotheses, legal-role interpretation, extraction, comparison, and synthesis.
- Model-generated interpretation must never silently overwrite primary-source facts.
- Supporting and adverse authority are both required in material legal research.
- Do not expose or depend on hidden chain-of-thought; persist actions, structured outputs, evidence, configuration, and factual execution traces instead.

## Architecture fitness discipline

JurisNexo uses executable architecture constraints modeled after the Request Engine approach.

`docs/testing/current-guarantees.toml` is the durable semantic guarantee inventory. It names guarantees and required evidence classes, not exact test files.

`docs/22-architecture-fitness-functions.md` defines which structural rules belong in blocking deterministic fitness functions. Current fitness tests live under `backend/tests/architecture/` and must remain explicitly gated in CI.

Classify rules before changing them:

```text
HARD        security/provenance/legal-quality invariant; fail closed by default
CONTROLLED  accepted architecture/product shape; evolve explicitly with docs + proof
FLEXIBLE    private implementation detail; do not freeze gratuitously
HISTORICAL  prior implementation/benchmark evidence; not automatically current authority
```

When an architecture fitness test fails, do not mechanically weaken the test, widen an allowlist, move code into a generic shared bucket, or hide a dependency. First identify the protected guarantee and decide whether the implementation drifted or the accepted architecture intentionally changed.

For intentional architecture evolution, update the normative docs, guarantee inventory when semantics change, and the executable fitness function coherently in the same change. Preserve or strengthen the protected evidence.

Architecture tests are structural evidence only. They do not replace real PostgreSQL/security invariants or semantic legal benchmarks.

## Ingestion design gate

Before implementing or changing an ingestion capability, identify:

```text
Source artifact/version/checksum
Document workspace capabilities required
Structure discovery output
Structure audit gate
Decision/case boundary representation
Extraction layer(s)
Extraction audit gate
Typed evidence produced
Canonical commit permissions
Failure/retry states
Benchmark proving the change
```

Do not create one-shot extraction that conflates faithful source reconstruction, metadata extraction, legal semantic enrichment, and verification unless a benchmark proves it is superior.

For evidence, avoid semantically ambiguous parallel arrays. Prefer typed objects that explicitly distinguish source/index evidence, observed destination/content evidence, and derived interpretation.

## Research design gate

Before changing the research agent, identify:

```text
Research question/brief contract
Retrieval channel(s)
Candidate funnel
Specialist role(s)
Adverse-authority search
Citation/later-treatment traversal
Evidence records consumed/created
Completion/sufficiency contract
Claim verification gate
Budget/failure semantics
Benchmark and human/product metric affected
```

Do not optimize only for finding supporting authorities.

## Guardrails versus invariants

Classify every protection before implementing it.

Use SDK/agent guardrails for semantic/runtime checks such as malformed tool requests, unsupported claims, role confusion, or bounded safety checks.

Use deterministic application/API/database controls for:

- authorization and tenant scope;
- valid artifact/document/case/page identity;
- checksum and source membership;
- foreign keys/constraints;
- allowed state transitions;
- canonical-write permissions;
- quota/billing enforcement;
- production credential boundaries.

Never move a HARD system invariant into an LLM-only guardrail.

## Provider/model capability gate

Before assigning a provider/model to an agent role, verify the capabilities that role actually requires:

```text
structured output fidelity
function/tool calling
handoffs / agents-as-tools behavior
multimodal/PDF/image support
context/token limits
usage accounting
retry/error semantics
tracing visibility
SDK adapter maturity
cost/latency
```

Do not infer feature parity from the fact that the Agents SDK can call the provider. Record/provider-pin benchmarked configurations where reproducibility matters.

## Research-method discipline

The repository references RLM, generator-verifier/critic patterns, hybrid retrieval/RRF, Legal Elements, HYPO/CATO, KELLER/LegalSearchLM, CaseGNN, CaseLink, RAPTOR, DocETL, LOTUS, and GraphRAG/LegalGraphRAG.

These are research influences, not requirements to implement every framework.

A method earns production complexity only when:

1. it targets an observed failure/bottleneck;
2. it has a simpler/current baseline;
3. an independent benchmark measures the claimed improvement;
4. the gain justifies cost, latency, maintenance, and new failure modes.

See `docs/17-agent-methodology-and-benchmark-map.md`.

## Benchmark and evidence discipline

A workflow exiting successfully is not proof of semantic success.

Keep distinct:

```text
runtime/provider status
navigation/mechanical status
semantic/evidence status
overall research/product validation
```

For meaningful agent/retrieval changes:

- preserve frozen inputs/gold where applicable;
- do not leak gold answers into prompts/tools;
- compare to the current baseline;
- classify misses by failure layer;
- record model/provider/configuration, corpus/source version, token/cost usage, and evidence trace;
- prefer separate targeted benchmarks for separate hypotheses rather than hoping one stochastic run exercises every capability.

Never weaken a scorer merely to make a run green. Fix an ambiguous contract explicitly, version it when necessary, and retain adversarial cases.

## Test evidence discipline

Tests and benchmarks must prove the guarantee they claim.

Before adding/changing durable proof, identify:

```text
protected guarantee/risk
plausible defect that must fail the test
real execution boundary
independent oracle/gold where appropriate
important authoritative state/evidence
canonical CI lane
```

Do not compute the expected result using the same production logic being tested. Do not substitute mocks when the claimed guarantee depends on PostgreSQL constraints, authorization, provider behavior, or real document semantics.

## Database and CI isolation discipline — mandatory

Canonical repository CI uses a **fresh ephemeral PostgreSQL database** created for the workflow run. It must prove clean reproduction through migrations + bootstrap and must destroy the test database/volume afterward.

Normal PR/main CI must not depend on, read from, or mutate the shared cloud development database. Development/staging/production database checks belong in separate explicit deployment, smoke, or read-only audit workflows and are not substitutes for ephemeral CI.

When reporting database checks, distinguish these claims precisely:

```text
ephemeral CI green
    = repository migrations/bootstrap/tests reproduce on a clean database

environment smoke/deploy green
    = that specific external database is reachable/migrated/healthy
```

Do not infer one from the other.

The canonical PostgreSQL configuration inputs are:

```text
POSTGRES_HOST
POSTGRES_PORT
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_SSLMODE
```

`DATABASE_URL` is not required. Migration/application URLs may be reconstructed from those component settings. `MIGRATION_DATABASE_URL` or `DATABASE_URL` may be used only as explicit compatibility/operational overrides when appropriate; do not introduce a second mandatory copy of the same credentials.

See `docs/27-database-bootstrap-and-multi-court-registry.md`.

## File and abstraction discipline

Prefer domain/capability names over generic dumping grounds.

Avoid adding broad `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, generic agent wrappers, generic repositories, or a second agent framework unless a concrete contract requires them.

The runtime should be replaceable. Do not persist SDK-specific objects as long-lived corpus/evidence records.

## Documentation rule

Repository documentation is the source of truth. When implementation discovers that an accepted contract is wrong or incomplete, update the relevant doc/ADR in the same coherent change rather than encoding a silent new architecture in code.

Do not use `AGENTS.md` as a duplicate architecture specification. Keep detailed rationale and durable contracts under `docs/` and update this file only when the operational map changes.

## Validation before completion

Run the narrowest relevant checks first, then the repository's canonical CI-equivalent checks.

Current backend quality/database/runtime checks are defined in `.github/workflows/ci.yml` and include:

- Ruff for backend and benchmark runners;
- blocking `pytest tests/architecture` architecture fitness functions;
- Pyright strict checking;
- backend tests against an ephemeral PostgreSQL instance through Docker Compose;
- historical benchmark scorer smoke tests;
- targeted boundary discrepancy scorer smoke tests;
- API/Docker runtime health smoke test;
- final `CI aggregate` gate.

For PR work, exact-head GitHub `CI aggregate` is authoritative merge evidence.

Do not claim semantic benchmark parity or architecture completion merely because repository CI is green.
