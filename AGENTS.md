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
3. `docs/01-system-architecture.md` — platform boundaries;
4. `docs/13-agent-runtime-and-multi-agent-orchestration.md` — canonical agent-runtime/orchestration contract;
5. `docs/15-ingestion-agent-pipeline.md` — Structure -> Audit -> Extraction -> Audit pipeline;
6. `docs/16-corpus-api-agent-contract.md` — stable agent/data boundary;
7. `docs/20-agents-sdk-provider-and-guardrail-compatibility.md` — provider/SDK capability constraints;
8. `docs/21-implementation-governance-and-agent-execution.md` — implementation sequencing and migration discipline;
9. `docs/22-architecture-fitness-functions.md` and `docs/testing/current-guarantees.toml` — executable architecture policy and normative guarantee inventory;
10. `docs/02-legal-corpus-and-data-model.md` when changing persisted legal/corpus data;
11. `docs/03-research-agent-and-report-contract.md` when changing legal research behavior;
12. `docs/10-job-state-machines-and-reproducibility.md` when changing long-running jobs or durable execution;
13. `docs/11-benchmark-annotation-and-evaluation-protocol.md` and `docs/17-agent-methodology-and-benchmark-map.md` when changing benchmarks, retrieval, agent behavior, or research methods;
14. `docs/05-security-privacy-and-trust.md` and `docs/09-tenancy-authentication-and-access-control.md` for trust/tenant-sensitive changes;
15. `docs/18-migration-plan-custom-harness-to-agents-sdk.md` for runtime migration work.

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
- backend tests against PostgreSQL through Docker Compose;
- historical benchmark scorer smoke tests;
- targeted boundary discrepancy scorer smoke tests;
- API/Docker runtime health smoke test;
- final `CI aggregate` gate.

For PR work, exact-head GitHub `CI aggregate` is authoritative merge evidence.

Do not claim semantic benchmark parity or architecture completion merely because repository CI is green.
