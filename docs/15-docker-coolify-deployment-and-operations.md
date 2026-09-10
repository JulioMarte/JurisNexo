# JurisNexo — Docker, Coolify, Deployment, and Operations

## 1. Purpose

JurisNexo will run as a Dockerized application deployed behind Coolify.

This document defines the deployment contract so local development, CI, and production use the same container boundaries and so Coolify remains an orchestrator rather than the only place where runtime behavior is described.

The repository-owned Docker Compose definition is the deployment source of truth.

## 2. Deployment principle

Production deployment should use a **Git-backed Docker Compose Application in Coolify**.

Reasons:

- the Compose file remains versioned with the application;
- branch-based deployments and webhooks are available;
- service builds, commands, environment references, volumes, health checks and networking remain reviewable in Git;
- production topology can be reproduced outside Coolify if necessary.

Do not make the production stack depend on a Compose definition that exists only inside the Coolify UI.

## 3. Initial production topology

Recommended application containers:

```text
coolify / reverse proxy
        |
        +--> web       Next.js
        |
        +--> api       FastAPI
                     |
                     +--> external managed PostgreSQL/Supabase
                     +--> external object storage/Supabase
                     +--> redis
                     +--> model providers

worker  background jobs; not publicly routed
redis   queue/cache transport; internal only
```

The first deployment may therefore contain these Compose services:

```text
web
api
worker
redis
```

PostgreSQL/Auth/Storage may remain external through Supabase during the MVP. They do not need to run inside the Coolify stack merely to satisfy the “everything is Dockerized” rule; the JurisNexo-owned executable components must be containerized, while managed external infrastructure is consumed over documented interfaces.

If the project later self-hosts PostgreSQL or storage, add those as separately managed stateful resources with explicit backup/recovery procedures.

## 4. Compose ownership

`compose.yaml` is the production-shaped baseline.

`compose.dev.yaml` may add development-only behavior such as:

- bind mounts;
- hot reload;
- local PostgreSQL;
- local object-storage emulator when useful;
- debug ports;
- development commands.

Production behavior must never rely on `compose.dev.yaml`.

Recommended pattern:

```text
compose.yaml        portable production topology
compose.dev.yaml    local overrides only
```

Coolify should point to the repository's production Compose file.

## 5. Build policy

Maintain separate production Dockerfiles for materially different runtime images:

```text
deploy/docker/web.Dockerfile
deploy/docker/api.Dockerfile
deploy/docker/worker.Dockerfile
```

The API and worker may share a common Python builder/base stage, but must have explicit final commands.

Images should be:

- multi-stage where useful;
- deterministic from committed lockfiles;
- non-root where practical;
- free of source-control metadata/secrets;
- minimal but still contain binaries required by health checks;
- reproducible in GitHub Actions and Coolify.

Do not install production dependencies dynamically at container startup.

## 6. Web container contract

The Next.js production container should:

- build from the committed frontend lockfile;
- generate a production build during image construction;
- listen on `0.0.0.0`;
- expose one documented internal port;
- implement a lightweight health endpoint;
- receive API/public configuration only through runtime-safe environment variables where feasible.

Avoid baking secrets into `NEXT_PUBLIC_*` variables. Anything exposed with a public frontend prefix is considered public configuration.

## 7. API container contract

The FastAPI container should:

- start one production ASGI server command;
- listen on `0.0.0.0`;
- expose a `/health/live` endpoint for process liveness;
- expose a `/health/ready` endpoint for readiness;
- avoid performing long migrations or corpus jobs as part of ordinary startup;
- terminate gracefully so in-flight HTTP work can finish within deployment limits.

Readiness should verify only dependencies required to safely accept traffic and remain cheap. It should not call external LLM providers on every probe.

## 8. Worker container contract

The worker image uses the same versioned backend package as the API but a different entrypoint.

The worker must:

- have no public domain/port;
- receive an explicit worker identity/role;
- use least-privilege database credentials;
- inherit immutable `job_id`/`organization_id` execution scope for tenant work;
- handle graceful termination;
- expose health status using an internal process-specific health command when feasible;
- avoid unrestricted Supabase service-role authority for ordinary tenant research.

If Celery is the initial queue implementation, keep Celery task signatures thin and call domain/application use cases rather than putting legal logic inside task decorators.

## 9. Redis contract

Redis is an internal runtime dependency when Celery is used.

Do not publish Redis to the Internet.

Within the Compose stack, services should connect by Compose service DNS name rather than host-published ports.

If Redis persistence is not required for the selected queue semantics, do not treat Redis as the product source of truth. PostgreSQL owns research state, evidence, report state and audit history.

## 10. Networking

Coolify/Compose networking should follow least exposure:

```text
public:
  web
  api (directly or only through web, depending on routing choice)

internal only:
  worker
  redis
```

Do not add `ports:` for internal-only services unless required for a deliberate operational reason.

Services within one Compose stack can communicate through service names on the Compose network.

The application process must bind to `0.0.0.0`, not only `127.0.0.1`, for Coolify's proxy to reach it.

## 11. Routing model

Two supported production routing patterns are acceptable.

### Preferred simple model

```text
jurisnexo.quisqueyatech.com        -> web
api.jurisnexo.quisqueyatech.com    -> api
```

Advantages:

- clear browser/API separation;
- easier health and operational diagnosis;
- API remains reusable for future integrations.

### Same-host path model

```text
jurisnexo.quisqueyatech.com        -> web
jurisnexo.quisqueyatech.com/api/*  -> api
```

This is acceptable if routing/cookies/CORS are simpler for the chosen authentication flow.

The selected production route should be documented in the deployment environment; domain choice is not a domain-layer concern.

## 12. Health checks

For Docker Compose deployments, define health checks in Dockerfiles or Compose. Do not depend on a Coolify dashboard-only health-check configuration.

Recommended checks:

```text
web     GET /api/health or equivalent internal endpoint
api     GET /health/ready
redis   redis-cli ping
worker  process/queue worker ping or dedicated internal command
```

Use Docker `healthcheck` with reasonable startup grace, timeout and retries.

A one-time migration service, if introduced, should be excluded from determining long-lived application health.

Health checks must be meaningful but cheap. Never run legal retrieval benchmarks, OCR, model calls or migrations as health probes.

## 13. Startup ordering and readiness

Compose `depends_on` is not a substitute for application readiness.

The API and worker must tolerate dependencies becoming available slightly later and should use bounded retries where appropriate.

When using Compose health dependencies, use them only as an additional startup aid.

The system must recover correctly after:

- Redis restart;
- API restart;
- worker restart;
- deployment replacement;
- temporary database/network interruption.

Persisted research state in PostgreSQL is what allows recovery decisions to be made safely.

## 14. Database migrations

Migrations are repository-owned Alembic migrations.

Do not run arbitrary schema changes manually from the Supabase or Coolify dashboards as the normal deployment process.

Preferred deployment flow:

```text
CI validates migration chain
      |
      v
production images built
      |
      v
gated migration command/job
      |
      v
api/worker rollout
```

For the MVP, the exact migration invocation may be a one-shot container or a Coolify pre/post-deploy command, but it must execute the same Alembic command validated in CI.

Requirements:

- migrations are backward-aware where rolling overlap can occur;
- destructive changes require an explicit data-migration plan;
- migration failure blocks application promotion;
- schema state is never inferred from ORM auto-create behavior.

## 15. Environment variables and secrets

Commit only `.env.example` with non-secret names/documentation.

Actual production values live in Coolify/environment secret management and external provider configuration.

Classify configuration:

```text
public frontend config
backend non-secret config
backend secret config
worker secret config
build-time config
```

Examples of secrets:

- database credentials;
- JWT verification/issuer secrets where applicable;
- object-storage secret keys;
- LLM provider keys;
- reranker/embedding API keys;
- Sentry DSN if treated as non-public for backend use;
- Coolify deploy webhook/API tokens.

Secrets must not be passed as Docker build arguments when runtime environment variables or secret mechanisms suffice.

## 16. Coolify environment mapping

Coolify should manage at least separate logical environments:

```text
production
staging (when introduced)
```

The initial controlled demo may operate only production plus local/CI until real staging provides operational value.

Environment-specific values include:

- domains;
- database endpoints/roles;
- storage endpoints;
- auth issuer/audience;
- model provider keys;
- quotas/budgets;
- observability exporters;
- allowed origins.

Do not fork source-code configuration files per environment.

## 17. Automatic deployment and CI gating

Coolify supports automatic deployments from Git provider events, but JurisNexo should avoid deploying a commit merely because it was pushed if required CI has not completed.

Preferred production model:

```text
PR
  -> GitHub Actions CI
  -> merge to protected main
  -> canonical main CI
  -> authenticated Coolify deploy trigger
  -> Coolify builds/deploys repository Compose revision
```

Two operational implementations are acceptable:

### Option A — CI-triggered Coolify deployment (preferred)

Disable unconditional production Auto Deploy and let the final GitHub Actions deployment job call Coolify's authenticated deploy webhook only after release-blocking jobs succeed.

This provides the strongest connection between tested SHA and deployed SHA.

### Option B — Coolify Git auto-deploy

Use Coolify's Git integration to auto-deploy protected `main` after pushes.

This is simpler but relies on branch protection and merge-time CI rather than an explicit post-CI deployment gate.

For JurisNexo, Option A is preferred once production users depend on the system.

## 18. Monorepo watch paths

Coolify supports path-based deployment filtering for Git-backed applications.

If web/API are eventually represented as separate Coolify applications, configure watch paths so documentation-only or unrelated changes do not rebuild every component.

For a single repository-backed Compose application, prefer one coordinated deployment initially because API/worker contracts and migrations may need to move together.

Do not optimize deployment granularity before build times or release coupling become a real problem.

## 19. Persistent storage

Containers are disposable.

JurisNexo should minimize server-local persistent state during the MVP by keeping primary persistence in managed PostgreSQL/object storage.

If a Compose service needs persistence, declare it explicitly in Compose using named volumes or intentional bind mounts.

Never rely on files written only inside a container layer.

Potential local persistent state includes:

- Redis data only if the chosen queue policy requires it;
- temporary caches that can be reconstructed;
- future self-hosted services.

Primary legal artifacts and tenant uploads belong in durable object storage, not an API/worker container volume.

## 20. Backups and disaster recovery

A persistent Docker volume is not a backup.

For every stateful production component document:

- what is backed up;
- backup frequency;
- retention;
- encryption/access;
- restore procedure;
- restore-test cadence;
- acceptable recovery point/time objectives when the product matures.

For the MVP, highest priority is:

1. PostgreSQL data and migrations;
2. immutable source artifacts/private uploads;
3. report/evidence exports where not fully reconstructable from database/object storage;
4. Coolify configuration/secrets operational recovery.

Redis should not contain the only copy of a legally meaningful state transition.

## 21. Logging and observability

Containers log to stdout/stderr in structured form where practical.

Every request/job should propagate correlation metadata such as:

```text
request_id
job_id
organization_id (safe identifier only)
worker execution id
trace id
```

Never log:

- document contents by default;
- raw private user uploads;
- LLM provider API keys;
- access tokens;
- database passwords;
- unrestricted prompt payloads containing sensitive tenant material unless an explicit redacted/debug policy permits it.

OpenTelemetry should be initialized in API and worker processes so cross-process work can later be traced through supported propagation mechanisms.

## 22. Resource isolation and scaling

Coolify/Docker should permit API and worker resources to scale independently.

The first likely scaling pressure is expected in workers, not HTTP API.

Potential future worker separation:

```text
worker-research
worker-ingestion
worker-ocr
```

Do not split them until CPU/memory/concurrency behavior demonstrates a need.

OCR/document parsing can have different resource characteristics from LLM/network-heavy research; this is the strongest likely reason for future worker-pool specialization.

## 23. Deployment smoke test

Every deployment should be considered incomplete until a lightweight smoke sequence succeeds:

```text
web responds
api liveness responds
api readiness responds
database migration version is expected
auth/JWT validation works
worker is consuming the expected queue
one safe database read/write contract succeeds
```

Production smoke tests must not create uncontrolled paid model usage.

A synthetic research smoke job may be added later using a bounded fixture/provider configuration.

## 24. Rollback policy

Application rollback should mean deploying a known previously built/known-good source revision or image set.

Database rollback is different and cannot be assumed to be safely reversible.

Therefore schema changes should prefer expand/migrate/contract patterns when destructive changes could make an older application revision incompatible.

Do not treat “redeploy previous container” as a complete rollback strategy if a migration has already changed data/schema incompatibly.

## 25. Coolify-specific operational rules

- Use the Git-backed Docker Compose application path so repository changes drive the Compose definition.
- Keep public service domains mapped to the correct internal listening ports.
- Define Compose health checks in source control.
- Keep internal services unexposed unless deliberately required.
- Define Compose-owned volumes in the Compose file; Coolify's storage view reflects, rather than replaces, those declarations.
- Use an authenticated external deploy webhook from CI when deployment must happen only after CI success.
- Use Coolify's Git integration/webhooks rather than ad hoc SSH deployment scripts.
- Test repository path/watch rules before relying on them for production deployments.

## 26. Initial production Compose shape

Conceptually:

```yaml
services:
  web:
    build:
      context: .
      dockerfile: deploy/docker/web.Dockerfile
    restart: unless-stopped
    healthcheck: ...

  api:
    build:
      context: .
      dockerfile: deploy/docker/api.Dockerfile
    restart: unless-stopped
    healthcheck: ...

  worker:
    build:
      context: .
      dockerfile: deploy/docker/worker.Dockerfile
    restart: unless-stopped
    healthcheck: ...

  redis:
    image: redis:<pinned-compatible-version>
    restart: unless-stopped
    healthcheck: ...
```

Exact image versions, ports and commands should be pinned when implementation begins. This document intentionally avoids pretending those details are settled before the actual scaffolding exists.

## 27. Definition of Done for deployment architecture

The Docker/Coolify contract is ready when:

- a clean checkout can build every production image;
- local Compose can start the product dependencies needed for development;
- GitHub Actions builds the same Dockerfiles used by Coolify;
- production Compose is repository-owned;
- public and internal services are correctly separated;
- every long-running service has a meaningful health check;
- migrations are explicit and CI-tested;
- secrets live outside Git;
- a worker/API restart cannot erase product state;
- Coolify can deploy a known Git revision without manual server-side source edits;
- a documented rollback and backup path exists before the demo contains valuable customer data.

## 28. External implementation references

The implementation should be validated against the current official Coolify documentation for:

- Git-backed Docker Compose applications;
- Docker Compose health checks;
- networking and internal service exposure;
- persistent storage;
- environment variables;
- Git automatic deployment and authenticated deploy webhooks;
- monorepo watch paths.

Coolify behavior can evolve; repository decisions should be updated when a platform change materially affects this deployment contract.