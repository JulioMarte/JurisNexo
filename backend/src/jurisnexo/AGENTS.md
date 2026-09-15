# JurisNexo backend Python — module guardrails

These instructions apply to `backend/src/jurisnexo/**` and refine the repository-root `AGENTS.md`.

## Architecture

New backend/API work follows `docs/24-python-module-and-api-architecture.md`.

Top-level ownership:

```text
bootstrap/   composition/settings only
entrypoints/ HTTP/worker/CLI trust/process boundaries
platform/    cross-cutting technical mechanics only
modules/     business/capability ownership
```

Prefer module-first, layer-second organization. A module may grow `domain`, `application`, `adapters`, `api` and `contracts` only when real code requires those boundaries.

## Hard dependency direction

- domain must not import FastAPI, SQLAlchemy/psycopg, S3/model SDKs, bootstrap or API DTOs;
- application must not import FastAPI, concrete adapters or bootstrap;
- adapters depend inward on ports/contracts/domain values;
- entrypoints compose supported module surfaces and do not own business policy;
- bootstrap is a composition root, never a service locator;
- platform must not absorb legal/source/dataset/job business semantics.

Do not hide coupling with service locators, runtime imports, re-export facades or forwarding wrappers.

## Naming and file discipline

Avoid generic business dumping grounds such as `services.py`, `managers.py`, `helpers.py`, `utils.py`, `common.py`, universal repositories or a shared business-model package.

Keep HTTP/tool DTOs, application commands/queries, domain values, cross-module contracts and persistence mappings distinct even when fields happen to match.

## Database and I/O

PostgreSQL owns structural/transactional truth; Python owns semantic workflows and transaction framing. Use real PostgreSQL evidence for constraints, locks, scope/tenant isolation and concurrency claims.

Never hold authoritative DB locks while calling SCJ/TC portals, Backblaze/S3 or model providers. Persist durable work/outbox facts, commit, then perform external I/O.

Agents do not receive unrestricted SQL or storage credentials.

## Migration discipline

The existing top-level packages (`acquisition`, `corpus`, `ingestion`, `model_providers`) are migrated only in focused changes with tests and ownership clarity. Do not duplicate their implementation into `modules/` merely to make the directory tree look complete.
