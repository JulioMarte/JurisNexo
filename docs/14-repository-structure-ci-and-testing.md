# JurisNexo — Repository Structure, CI, and Testing

## 1. Purpose

This document defines how JurisNexo source code is organized, tested, and promoted through CI.

The structure is inspired by the engineering discipline used in `request-engine`: src-layout Python packaging, explicit entrypoints, domain modules, Alembic migrations, `uv`, Ruff, Pyright strict, semantically marked pytest suites, and CI as an evidence-producing gate rather than a single opaque test command.

JurisNexo adapts those ideas to a different product shape: a Python legal-research backend, a Next.js frontend, retrieval/evaluation workloads, document ingestion, background workers, and Docker/Coolify deployment.

## 2. Repository philosophy

JurisNexo is one repository and one product, but contains multiple runtime processes.

Do not create separate repositories for the API, worker, ingestion pipeline, retrieval service, or frontend during the MVP.

The repository should make boundaries obvious without forcing network boundaries.

## 3. Target repository layout

```text
JurisNexo/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── docker.yml
│   │   └── deploy.yml              # optional gated Coolify trigger
│   └── copilot-instructions.md     # optional repository guidance
│
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── src/
│   │   └── jurisnexo/
│   │       ├── __init__.py
│   │       ├── bootstrap/
│   │       ├── entrypoints/
│   │       │   ├── api/
│   │       │   ├── worker/
│   │       │   └── cli/
│   │       ├── modules/
│   │       │   ├── corpus/
│   │       │   ├── tenancy/
│   │       │   ├── research/
│   │       │   ├── reports/
│   │       │   ├── feedback/
│   │       │   └── usage/
│   │       └── platform/
│   │           ├── db/
│   │           ├── auth/
│   │           ├── storage/
│   │           ├── models/
│   │           ├── observability/
│   │           └── workflows/
│   ├── migrations/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       ├── security/
│       ├── retrieval/
│       ├── ingestion/
│       └── e2e/
│
├── web/
│   ├── package.json
│   ├── lockfile
│   ├── next.config.*
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── features/
│   │   ├── lib/
│   │   └── styles/
│   └── tests/
│       ├── unit/
│       └── e2e/
│
├── benchmark/
│   ├── datasets/
│   ├── annotations/
│   ├── retrieval/
│   ├── ingestion/
│   └── reports/
│
├── scripts/
│   ├── ci/
│   ├── corpus/
│   ├── benchmark/
│   └── dev/
│
├── deploy/
│   ├── docker/
│   │   ├── api.Dockerfile
│   │   ├── worker.Dockerfile
│   │   └── web.Dockerfile
│   └── coolify/
│       └── README.md
│
├── docs/
├── compose.yaml
├── compose.dev.yaml
├── .env.example
├── .dockerignore
├── .gitignore
├── AGENTS.md
├── CONTRIBUTING.md
└── README.md
```

Exact filenames may evolve, but the boundaries should remain recognizable.

## 4. Backend modular-monolith structure

The backend follows a domain-module pattern similar in spirit to Request Engine, adapted to JurisNexo.

### `bootstrap/`

Composition root and application initialization.

Responsibilities may include:

- settings loading;
- database/session construction;
- provider adapter construction;
- workflow adapter registration;
- dependency wiring;
- logging/telemetry initialization.

Business behavior does not belong here.

### `entrypoints/`

Transport/process-specific entrypoints.

Examples:

```text
entrypoints/api       FastAPI application/routes
entrypoints/worker    background worker process
entrypoints/cli       administrative and corpus commands
```

Entrypoints call application/domain use cases. Domain modules must not import FastAPI, Celery, Coolify, or Docker concerns.

### `modules/`

Product/domain capabilities.

Initial modules:

```text
corpus
  source acquisition
  canonical identity
  normalized legal documents
  citations
  passages

research
  jobs
  briefing
  search planning
  case review
  adverse authority
  evidence verification
  report synthesis

tenancy
  organizations
  memberships
  authorization contracts

reports
  report versions
  rendering/export contracts

feedback
  professional evaluation feedback

usage
  quotas
  resource budgets
  provider usage accounting
```

A module may contain its own domain objects, application services, ports, and infrastructure adapters where useful.

### `platform/`

Cross-cutting infrastructure implementations, not legal business rules.

Examples:

- PostgreSQL connection/session machinery;
- Supabase/JWT authentication adapter;
- object storage adapter;
- model-provider adapters;
- tracing/logging;
- Celery/Temporal/Hatchet adapter;
- shared infrastructure utilities.

## 5. Dependency rules

The repository should enforce these structural expectations:

```text
entrypoints -> modules/application -> domain/contracts
                                   -> ports
platform/adapters ----------------> ports
```

Avoid:

```text
domain -> FastAPI
domain -> Celery
domain -> Supabase SDK
domain -> provider-specific LLM object
research -> raw browser session
web -> direct privileged SQL
```

The research runtime may consume retrieval/model/storage ports, but should not own credentials or infrastructure clients directly.

## 6. Python toolchain

Use a modern locked Python toolchain similar to Request Engine:

```text
Python 3.13+
uv
pyproject.toml
Ruff
Pyright strict
pytest
pytest-asyncio
```

Rules:

- commit `uv.lock`;
- CI uses `uv sync --frozen`;
- Ruff is the canonical formatter/linter;
- Pyright runs in strict mode unless a narrowly documented exception is required;
- dependencies use bounded compatible ranges rather than unbounded latest versions;
- production images install from the lockfile.

## 7. Frontend toolchain

Use:

```text
Node LTS
Next.js
TypeScript strict
ESLint
Playwright
```

Choose one JavaScript package manager and commit its lockfile. Do not allow multiple lockfile types in the repository.

Frontend CI must prove at minimum:

- dependency installation from lockfile;
- lint;
- TypeScript checking;
- unit/component tests if present;
- production Next.js build;
- Playwright for selected product journeys.

## 8. Test taxonomy

Tests are categorized by the correctness property they prove, not only by directory.

Recommended pytest markers:

```text
unit
postgres
integration
contract
e2e
security
tenancy
invariant
provenance
retrieval
ingestion
workflow
model
slow
benchmark
adversarial
```

### Unit

Pure/isolated behavior with no network or real database requirement.

Examples:

- legal-reference parsing;
- canonical identity normalization;
- RRF fusion;
- job-state transition rules;
- evidence completeness rules;
- report-claim validation.

### PostgreSQL/integration

Run against a real PostgreSQL instance with the extensions used in production.

Must prove:

- migrations from zero to head;
- schema constraints;
- pgvector operations;
- FTS behavior/contracts;
- tenant-aware repositories;
- state transitions;
- immutable report/evidence behavior.

Do not replace these tests with SQLite.

### Security/tenancy

These are release-blocking invariants.

At minimum:

- Org A cannot read Org B jobs;
- Org A cannot read Org B uploads;
- Org A cannot read Org B evidence/reports;
- workers cannot widen their immutable execution scope;
- public corpus queries do not accidentally join private data;
- membership removal changes access immediately;
- browser/client credentials cannot access privileged internal tables;
- private artifacts cannot become globally reusable corpus knowledge implicitly.

### Retrieval

Two distinct layers exist.

**Contract tests** prove deterministic search behavior, filters, citation lookup, profile versioning and stable result schemas.

**Benchmark tests** measure quality and should use the protocol in `11-benchmark-annotation-and-evaluation-protocol.md`.

Metrics may include:

- Recall@K;
- MRR/NDCG where appropriate;
- Critical Miss Rate;
- adverse-authority recall;
- citation resolution accuracy;
- reranker improvement;
- latency/cost.

Not every benchmark should block every small PR. A fast locked regression subset should be blocking; larger model/provider evaluations may run manually/nightly/release-candidate.

### Ingestion

Representative golden documents should prove:

- checksum/source preservation;
- page-count/page-boundary fidelity;
- extraction/OCR quality thresholds;
- canonical identity resolution;
- duplicate behavior;
- citation extraction;
- idempotent re-ingestion;
- versioned derived artifacts.

### Workflow

Must prove:

- retries do not duplicate artifacts;
- cancellation prevents future expensive work;
- budget exhaustion produces the documented terminal state;
- gap-assessment loops are bounded;
- completed reports cannot be silently mutated;
- failure classes remain observable and actionable.

### E2E

The canonical MVP journey is:

```text
sign in
 -> select/create organization
 -> submit research
 -> observe persisted progress
 -> receive report
 -> open cited evidence
 -> submit feedback
```

A production-like E2E suite should prove this across public entrypoints and real runtime database roles.

## 9. Testing model providers

CI must not depend on uncontrolled live LLM calls for ordinary correctness.

Use three layers:

1. deterministic fake/provider fixtures for unit and workflow tests;
2. recorded/contract fixtures where legally and operationally appropriate;
3. explicit live-provider benchmark/smoke jobs with budgets and secrets, not run on untrusted forks.

A model changing output should not make unrelated PR CI flaky.

Live model evaluation is evidence, not a substitute for deterministic tests.

## 10. CI philosophy

CI is a correctness and architecture gate.

Like Request Engine, JurisNexo should avoid a single monolithic command whose failure provides little diagnostic value.

Initial GitHub Actions jobs should be logically separated.

```text
backend-quality
frontend-quality
postgres-integration
security-tenancy
retrieval-regression
docker-build
e2e
ci-aggregate
```

The aggregate status is the branch-protection target.

## 11. Canonical CI workflow

### `backend-quality`

Runs:

```text
uv sync --frozen
ruff format --check
ruff check
pyright
pytest -m "unit or contract" fast subset
```

### `frontend-quality`

Runs locked install, lint, typecheck, tests, and production build.

### `postgres-integration`

Starts a real PostgreSQL service compatible with production requirements, enables required extensions, migrates from zero to head, and runs database/integration tests.

When practical, also prove downgrade/upgrade behavior for migrations that require it.

### `security-tenancy`

Runs tenant-isolation and least-privilege tests using multiple organizations and the same runtime roles expected in production.

This job is mandatory; security invariants must not be hidden inside an optional test suite.

### `retrieval-regression`

Runs a small locked, versioned legal retrieval evaluation dataset that is fast and deterministic enough for PR CI.

The job should record machine-readable metrics as an artifact and fail only against documented regression thresholds.

### `docker-build`

Builds the same Docker images used by Coolify:

```text
web
api
worker
```

It must fail if production Dockerfiles no longer build from a clean checkout.

### `e2e`

Starts the required stack using Docker Compose or an equivalent CI topology and exercises the core product journey.

Initially this may run only on `main`, release candidates, or when relevant paths change if runtime cost is significant.

### `ci-aggregate`

Depends on all release-blocking jobs and publishes one canonical pass/fail status.

This makes branch protection stable even when individual CI jobs evolve.

## 12. Pull request and branch behavior

Recommended initial branch model:

```text
main        deployable production/integration truth
feature/*   short-lived work branches
```

Do not add a permanent `development` branch merely because Request Engine has one unless JurisNexo's release process actually needs two long-lived integration states.

For the MVP, trunk-based development with protected `main` is simpler.

Required `main` protection should include:

- pull request before merge;
- aggregate CI success;
- no unresolved review requirements when enabled;
- branch up to date when materially required;
- no direct production secrets in repository variables/files.

If a staging environment later becomes operationally important, add an explicit release/staging model then.

## 13. CI triggers and concurrency

Run CI on:

```text
pull_request
push to main
workflow_dispatch
```

Use concurrency cancellation for superseded PR commits so obsolete model/integration jobs do not consume runner or provider budgets.

Use path filters only for expensive secondary jobs, not to accidentally skip fundamental repository quality gates.

## 14. CI evidence artifacts

Borrow Request Engine's evidence-oriented philosophy, but keep the first version simpler.

Produce machine-readable artifacts where they materially aid regression analysis:

```text
.ci/
  backend-quality.json
  frontend-quality.json
  postgres-integration.json
  security-tenancy.json
  retrieval-regression.json
  docker-build.json
  e2e.json
```

Retrieval and ingestion evaluations should also retain:

- dataset version;
- corpus/index generation;
- retrieval profile;
- model identifiers where relevant;
- metrics;
- failure examples.

Do not build an elaborate evidence framework before these artifacts have consumers. Add sophistication incrementally.

## 15. Coverage policy

Line coverage is a diagnostic signal, not the primary quality target.

Release-critical correctness comes from invariant tests:

- tenant isolation;
- provenance;
- state-machine validity;
- evidence immutability;
- migration correctness;
- critical retrieval regressions;
- report claim traceability.

Do not optimize for an arbitrary global coverage percentage while leaving these boundaries untested.

## 16. Local developer contract

A developer should be able to start the required local stack with Docker Compose and run quality commands without installing PostgreSQL/Redis manually.

Expected commands may converge on a small canonical set, for example:

```text
docker compose -f compose.yaml -f compose.dev.yaml up -d
cd backend && uv sync --frozen
cd backend && uv run pytest
cd web && <package-manager> install --frozen-lockfile
```

Repository scripts/Makefile/task-runner aliases may be added for ergonomics, but CI should execute the underlying canonical tools so behavior remains inspectable.

## 17. Definition of Done for repository engineering

The engineering skeleton is ready when:

- backend uses a `src/jurisnexo` layout;
- frontend and backend have locked dependencies;
- migrations run from a clean PostgreSQL database;
- real tenant-isolation tests pass;
- retrieval regression fixtures exist;
- production Docker images build in CI;
- an end-to-end Compose stack can be started from a clean checkout;
- branch protection can depend on a stable aggregate CI result;
- no production deployment requires manual mutation of source files on the Coolify server.