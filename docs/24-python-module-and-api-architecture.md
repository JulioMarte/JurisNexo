# JurisNexo — Python module and API architecture

Status: normative for new backend/API organization. This adopts the proven organizational principles from Request Engine `development` while preserving JurisNexo's legal-corpus, provenance, ingestion and agent guarantees.

## 1. Decision

JurisNexo is a **modular monolith**, organized **module first, layer second**.

```text
backend/src/jurisnexo/
├── bootstrap/       # settings and composition roots only
├── entrypoints/     # HTTP / worker / CLI process and trust boundaries
├── platform/        # genuinely cross-cutting technical mechanics
└── modules/         # business/capability ownership
```

This is not a microservice split. Modules may share one Python process and one PostgreSQL database, and a correctness-sensitive operation may use one authoritative transaction across module-owned state when the invariant requires it.

The structure is copied as a **design discipline**, not as Request Engine business code. JurisNexo keeps its own domain vocabulary and guarantees.

## 2. Initial module ownership

The initial capability modules are:

- `source_catalog`: official institutions, source registries, collections, discovery policy and source-native records. Knowing that a source record exists does not mean it has been acquired or published to agents.
- `acquisition`: discovery/acquisition orchestration, source synchronization policy and artifact acquisition lifecycle. Source-specific connectors belong outward in adapters as the module grows.
- `corpus`: canonical legal documents, judicial decisions/proceedings, provenance, identity resolution, evidence and legal relationships.
- `datasets`: dataset definitions, immutable/frozen snapshots and membership/manifests over the canonical corpus. A dataset is not a copied S3 folder.
- `jobs`: durable job definitions, schedules, runs, retries and operational execution facts. The scheduler creates work; it does not own ingestion or agent semantics.
- `ingestion`: document processing semantics and the mandatory Structure -> Structure Audit -> Extraction -> Extraction Audit -> canonical commit gates.
- `agent_runs`: agent profiles/run requests and the binding of a dataset snapshot + agent profile + run configuration. Model/runtime SDK objects are not durable corpus truth.

This inventory is CONTROLLED and may evolve deliberately. Do not create modules merely because a noun exists; add ownership only when a real capability requires it.

## 3. Growth shape inside a module

A module grows structure only as needed:

```text
modules/<module>/
├── domain/
├── application/
│   ├── commands/
│   ├── queries/
│   └── ports/
├── adapters/
│   ├── db/
│   └── providers/
├── api/
├── contracts/
└── README.md
```

Meanings:

- `domain`: framework-independent rules/types/policies owned by the module;
- `application`: semantic commands/queries and use-case orchestration;
- `application/ports`: capabilities required by application/domain code;
- `adapters/db`: PostgreSQL/SQLAlchemy implementations and correctness-sensitive SQL;
- `adapters/providers`: source portals, S3, model/provider SDK adapters where module-owned;
- `api`: module-owned HTTP/tool DTOs and router composition;
- `contracts`: intentionally published cross-module values/protocols.

Do not eagerly generate every directory. Prefer a small cohesive module until real code justifies more layers.

## 4. Dependency direction

Preferred direction:

```text
HTTP / worker / provider adapters
            ↓
       application
            ↓
 domain + application ports
            ↑
 DB/provider adapters
```

Rules:

- domain must not import FastAPI, SQLAlchemy, psycopg, boto SDKs, model SDKs, bootstrap or API DTOs;
- application must not import FastAPI, concrete DB/provider adapters or bootstrap;
- adapters may depend inward on application ports/contracts/domain values;
- `entrypoints` compose supported module APIs; they do not become a parallel business layer;
- `bootstrap` is a composition root, never a service locator imported from business code;
- cross-module dependencies use the target module's intentionally published `contracts`, not its internals.

Do not hide coupling with runtime imports, generic service locators, forwarding wrappers, `utils.py`, `helpers.py`, `common.py`, universal repositories or generic managers.

## 5. Platform boundary

`platform/` contains cross-cutting technical mechanics only:

```text
platform/db
platform/storage
platform/http
platform/observability
platform/security
platform/scheduling
platform/idempotency
platform/outbox
```

Platform may own connection/session mechanics, signed-object access, telemetry, generic authentication primitives, scheduler/lease mechanics, idempotency storage mechanics and outbox transport mechanics.

Platform does **not** own why an SCJ decision exists, whether a source collection is active, which documents belong to a dataset, whether an ingestion audit passed, or which legal relation is canonical.

Backblaze/S3 is a storage adapter, not the corpus catalog or legal system of record.

## 6. Entrypoints

- `entrypoints/http`: FastAPI process/trust boundary, global middleware/error mapping, auth extraction and module router installation.
- `entrypoints/worker`: worker process startup and runtime composition. Business semantics stay in modules.
- `entrypoints/cli`: explicit operator/developer commands.

The HTTP app should be intentionally thin. Route handlers map transport DTOs to application commands/queries and map results back; they do not contain persistence or legal-domain workflows.

## 7. Database boundary

JurisNexo adopts the useful Request Engine principle that PostgreSQL is **authoritative structured state**, not dumb storage and not a second application backend.

Python/application owns:

- semantic commands/queries and orchestration;
- authorization and capability policy;
- transaction framing;
- source/identity/reconciliation policy;
- provider/network orchestration;
- API/tool DTO mapping.

PostgreSQL owns:

- PK/FK/UNIQUE/CHECK and structural truth;
- scope/tenant integrity backstops;
- atomicity, row/range locks and revisions;
- durable job/idempotency/outbox/audit facts;
- narrow correctness backstops close to the data.

Forbidden patterns:

```text
table == public API resource
Pydantic DTO == domain type == persistence row
PATCH arbitrary canonical fields
generic CRUD over authoritative legal tables
workflow-sized stored procedures duplicating Python orchestration
network calls from PostgreSQL
hidden independent transactions inside helpers/repositories
```

For correctness-sensitive writes, make the reasoning visible:

```text
READ -> PLAN -> LOCK -> VALIDATE -> WRITE -> EMIT
```

Never hold authoritative database locks across SCJ/TC/S3/model-provider network calls.

## 8. API standards

The API is the supported boundary for the admin panel, agents and future clients.

### Resource shape

- version public/control-plane routes under `/v1`;
- plural resource nouns (`/v1/datasets`, `/v1/jobs`, `/v1/cases`);
- opaque UUID identifiers;
- path segments kebab-case; JSON/query fields snake_case;
- semantic commands use explicit POST actions, e.g. `POST /v1/jobs/{id}:run`;
- GET never mutates state;
- avoid deep nesting; relationships deeper than two levels become filters or dedicated resources.

### Lists

Every collection endpoint is paginated from day one and returns one envelope:

```json
{"data": [], "next_cursor": "opaque", "has_more": true}
```

No bare top-level arrays. Cursors are opaque and server-issued. Unknown filters/query parameters are rejected rather than silently ignored.

### Errors

Use one stable envelope:

```json
{
  "error": {
    "code": "stable_machine_code",
    "message": "human readable",
    "retryable": false,
    "resolution": "fix_request",
    "details": {},
    "request_id": "..."
  }
}
```

Clients never parse human messages. Stack traces, SQL text, storage credentials and provider exceptions never leave the process.

### Status discipline

- query: `200`;
- creation: `201`;
- accepted asynchronous work: `202` where the contract is explicitly asynchronous;
- malformed request: `400`;
- unauthenticated: `401`;
- authenticated but unauthorized: `403`;
- absent or deliberately non-disclosed resource: `404`;
- lifecycle/idempotency/revision conflict: `409`;
- rate limit / overload: `429` / `503` with `Retry-After`.

### Mutations

Mutating admin/control-plane operations should be idempotent where retries are plausible. For externally retryable commands, use `Idempotency-Key` and reject key/fingerprint reuse conflicts deterministically.

Where an aggregate uses optimistic concurrency, accept an expected revision and return a stable `409` conflict rather than silently overwriting newer state.

### OpenAPI

Every operation must have typed request/response models, stable `operationId`, summary, documented error responses and security metadata. The OpenAPI document is a contract and should eventually be frozen by executable tests.

Every response carries an `X-Correlation-ID`; error envelopes also expose it as `request_id`.

## 9. Agent and storage boundary

Normal agent access is:

```text
Agent -> Corpus/Dataset API -> authorized dataset snapshot -> legal capabilities
```

Agents do not receive PostgreSQL credentials.

Direct artifact reading, when needed, is a separate bounded capability:

```text
Agent -> Artifact API -> authorization/dataset membership -> short-lived signed read URL -> S3
```

Never grant agents general bucket credentials or bucket enumeration. Artifact bytes are addressed through canonical `artifact_id` values.

## 10. Ingestion versus agent processing

Keep two operational planes distinct:

```text
SOURCE / ACQUISITION PLANE
source -> discover -> acquire -> validate -> store -> process -> canonical corpus

DATASET / AGENT PLANE
canonical corpus -> dataset definition -> frozen snapshot -> agent/job -> run/result
```

A scraper does not become an agent tool merely because it exists. Acquisition connectors are infrastructure/source adapters. Research agents consume supported corpus capabilities.

## 11. Migration of current packages

Existing `jurisnexo.acquisition`, `jurisnexo.corpus`, `jurisnexo.ingestion`, `jurisnexo.model_providers` and top-level observability code are current implementation, not the desired permanent taxonomy.

Migration rule:

1. new control-plane/API work starts under this module-first structure;
2. move existing code only when its ownership is clear and tests can move with it;
3. do not create forwarding facades merely to make a tree look clean;
4. do not mix a large mechanical namespace migration with unrelated behavior changes;
5. preserve current benchmark/provenance guarantees while migrating.

The first structural change establishes the top-level `bootstrap/entrypoints/platform/modules` boundary and moves the HTTP composition root to `entrypoints/http`. Existing business packages are migrated in focused follow-up changes rather than copied into two authoritative homes.

## 12. API/control-plane implementation order

1. connection/settings + DB session mechanics;
2. consistent HTTP app/error/correlation infrastructure;
3. Source/Collection admin API;
4. ingestion/acquisition job and run API;
5. corpus inspection API;
6. dataset definition + immutable snapshot API;
7. agent/job run API over snapshot IDs;
8. admin UI over those APIs;
9. scheduled source reconciliation via job creation;
10. training/export derivations from frozen corpus snapshots.

The admin UI, workers, schedulers and agents all consume supported application/API contracts; none gets arbitrary database mutation authority.
