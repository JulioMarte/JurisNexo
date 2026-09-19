# JurisNexo production-code agent rules

Applies to `backend/src/jurisnexo/**` in addition to the repository-wide `AGENTS.md`.

This file is an operational map. Durable architecture belongs in `docs/`.

Before changing production code, identify the owning capability, affected guarantee IDs from `docs/testing/current-guarantees.toml`, the real authority boundary, and the proof that should catch a regression.

## Non-negotiable boundaries

- Primary legal sources and durable provenance are authoritative; model output is not.
- Agent/model runtimes do not own database authority, tenant identity, provenance validation, or canonical-write permission.
- Provider SDK types and Agents SDK runtime objects are infrastructure details and must not become durable corpus/evidence contracts.
- Corpus access crosses explicit application/corpus capabilities. Do not hand agents unrestricted SQL connections or production credentials.
- Canonical persistence must remain behind deterministic authorization, source/evidence validation, and required audit gates.
- Do not bypass mandatory ingestion stages by moving their authority into prompts, handoffs, or provider callbacks.

## Ownership and abstraction

Prefer capability/domain names over generic buckets. Do not create `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, generic repositories, or a second generic agent framework merely to make dependencies easier.

A new abstraction must make ownership, authority, failure handling, or testability clearer. A forwarding wrapper that only hides coupling is not an improvement.

## Engineering-quality signals

Read `docs/24-engineering-quality-signals.md` when a change adds a component connection, materially grows a Python file, or restructures package ownership.

The engineering-quality report exposes current top-level component imports, fan-in/fan-out, import sites, effective LOC, and large-file review candidates.

These measurements are sensors, not automatic refactor commands:

- do not split a cohesive file only because it exceeds the eLOC review threshold;
- do not hide a real dependency behind runtime imports, re-exports, service locators, or generic shared code to improve fan-in/fan-out;
- treat a new cross-component edge as review evidence: identify why the dependency exists and whether the source component remains the correct owner/coordinator;
- `HEALTHY_AS_IS` is a valid result when the measured structure is coherent;
- deterministic architecture, security, provenance, and legal-quality invariants remain independently blocking.

If structural code changes after reviewing a quality signal, rerun architecture fitness and the relevant behavioral proof.

## Provider/model changes

When touching `model_providers` or agent-runtime integration, verify the role actually requires and supports the relevant capabilities: structured outputs, tool calling, multimodal input, accounting, retry/error semantics, tracing, latency, and cost.

Provider compatibility is not inferred from API similarity. Keep provider-specific mechanics behind adapters and preserve model/provider/configuration metadata needed for reproducibility.

## Corpus and ingestion changes

For corpus/provenance/canonical-write changes, read the relevant current docs, especially:

- `docs/02-legal-corpus-and-data-model.md`
- `docs/15-ingestion-agent-pipeline.md`
- `docs/16-corpus-api-agent-contract.md`
- `docs/testing/current-guarantees.toml`
- `docs/testing/evidence-authoring-guide.md`

For a correctness-sensitive change, state the plausible defect and add/adapt the proof at the real execution boundary. Do not use a mock for the mechanism whose correctness is being claimed.

## Completion discipline

Run the narrowest relevant tests first, then the canonical CI-owned lane. Never report a proof as passing unless it actually ran on the intended code/environment. If a HARD guarantee is not fully proven, report the evidence gap explicitly rather than implying completion.

## Backend module and API architecture guardrails

These instructions apply to `backend/src/jurisnexo/**` and refine the repository-root `AGENTS.md`.

### Architecture

New backend/API work follows `docs/24-python-module-and-api-architecture.md`.

Top-level ownership:

```text
bootstrap/   composition/settings only
entrypoints/ HTTP/worker/CLI trust/process boundaries
platform/    cross-cutting technical mechanics only
modules/     business/capability ownership
```

Prefer module-first, layer-second organization. A module may grow `domain`, `application`, `adapters`, `api` and `contracts` only when real code requires those boundaries.

### Hard dependency direction

- domain must not import FastAPI, SQLAlchemy/psycopg, S3/model SDKs, bootstrap or API DTOs;
- application must not import FastAPI, concrete adapters or bootstrap;
- adapters depend inward on ports/contracts/domain values;
- entrypoints compose supported module surfaces and do not own business policy;
- bootstrap is a composition root, never a service locator;
- platform must not absorb legal/source/dataset/job business semantics.

Do not hide coupling with service locators, runtime imports, re-export facades or forwarding wrappers.

### Naming and file discipline

Avoid generic business dumping grounds such as `services.py`, `managers.py`, `helpers.py`, `utils.py`, `common.py`, universal repositories or a shared business-model package.

Keep HTTP/tool DTOs, application commands/queries, domain values, cross-module contracts and persistence mappings distinct even when fields happen to match.

### Database and I/O

PostgreSQL owns structural/transactional truth; Python owns semantic workflows and transaction framing. Use real PostgreSQL evidence for constraints, locks, scope/tenant isolation and concurrency claims.

Never hold authoritative DB locks while calling SCJ/TC portals, Backblaze/S3 or model providers. Persist durable work/outbox facts, commit, then perform external I/O.

Agents do not receive unrestricted SQL or storage credentials.

### Migration discipline

The existing top-level packages (`acquisition`, `corpus`, `ingestion`, `model_providers`) are migrated only in focused changes with tests and ownership clarity. Do not duplicate their implementation into `modules/` merely to make the directory tree look complete.
