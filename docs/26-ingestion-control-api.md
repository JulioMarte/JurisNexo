# 26 — Ingestion control API

Status: current implementation contract for the first operator-facing ingestion API.

## Purpose

This surface turns the existing source inventory, PostgreSQL provenance model and S3 object store into one controllable ingestion plane. It deliberately stops before semantic LLM processing. Acquisition and ingestion are separate stages.

The invariant remains:

```text
discovery != acquisition != processing != agent visibility
```

A discovered document is never downloaded merely because it exists. A source collection must explicitly have `acquisition_policy=enabled` before an acquisition run can be created.

## Ownership

```text
source_catalog
  official source registry
  collection policy
  discovered source-document inspection

acquisition
  durable acquisition runs/items
  bounded official HTTP fetch
  PDF validation + SHA-256
  content-addressed S3 object write
  artifact + provenance registration

platform/db
  short-lived PostgreSQL connections

entrypoints/http + bootstrap
  transport and composition only
```

The existing S3 adapter remains the concrete storage implementation during this slice. New application code sees only an object-store capability. Moving the legacy S3 implementation physically under `platform/storage` is intentionally deferred to a focused migration rather than creating a duplicate or forwarding facade.

## Source collection policy

`corpus.source_collections` is the operator policy layer over source-native collections. It does not replace `corpus.source_documents`.

Initial acquisition policies:

- `enabled`: new acquisition runs may select documents;
- `catalog_only`: inventory may exist but bytes are not acquired;
- `paused`: temporarily stop acquisition without losing configuration;
- `blocked`: acquisition is explicitly prohibited.

Agent visibility is independent: `hidden`, `discoverable`, or `searchable`.

Collections discovered before this migration are backfilled as `catalog_only` + `hidden`. Nothing historical becomes downloadable or agent-visible by migration side effect.

## Acquisition execution model

`POST /v1/acquisition-runs` creates a durable run and immutable set of run items. It does not perform network I/O inside that transaction.

`POST /v1/acquisition-runs/{id}:execute` then:

```text
claim run + commit
        ↓
HTTP fetch outside DB transaction
        ↓
validate PDF + compute SHA-256
        ↓
HEAD/PUT content-addressed S3 object
        ↓
short DB transaction registers artifact, locations and source-document link
        ↓
record item outcome
        ↓
finalize run counters/status
```

No authoritative PostgreSQL lock is held across HTTP or S3 I/O. If S3 succeeds and the following DB write fails, the object is a harmless content-addressed orphan; a retry can reuse it without duplicating bytes.

Current storage keys preserve the existing SCJ/TC namespaces and generalize safely for future source codes:

```text
jurisdictions/do/scj/<collection>/<sha-prefix>/<sha256>.pdf
jurisdictions/do/tc/<collection>/<sha-prefix>/<sha256>.pdf
jurisdictions/do/<source-code>/<collection>/<sha-prefix>/<sha256>.pdf
```

## HTTP surface

Current v1 endpoints:

```text
GET  /v1/sources
POST /v1/sources
POST /v1/sources/{id}:set-active

GET  /v1/source-collections
POST /v1/source-collections
POST /v1/source-collections/{id}:set-policy

GET  /v1/source-documents

POST /v1/acquisition-runs
GET  /v1/acquisition-runs
GET  /v1/acquisition-runs/{id}
GET  /v1/acquisition-runs/{id}/items
POST /v1/acquisition-runs/{id}:execute

GET  /v1/artifacts
```

Collection endpoints are cursor-paginated. Request bodies reject unknown fields. Mutation conflicts use stable 409 error codes. Every response receives `X-Correlation-ID`, and API failures use the JurisNexo error envelope.

## Runtime configuration

The API database connection is assembled from:

```text
POSTGRES_HOST
POSTGRES_PORT
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_SSLMODE
```

`DATABASE_URL` is not required by the API process. Alembic/integration-test tooling may continue using it independently.

Acquisition execution uses the existing `JURISNEXO_S3_*` contract. If S3 is not configured, inventory/admin reads still exist but execution reports runtime unavailability and readiness is not green.

The runtime image currently installs the exact boto3 version used by the dedicated S3 smoke workflow. This is an intentional transition constraint: once the legacy storage package is moved under `platform/storage`, boto3 should become an ordinary locked runtime dependency in the same focused change.

## Security boundary

This is an internal/admin API slice, not a public production authorization surface yet. Before Internet exposure, the source-management and acquisition command routes require operator authentication/capability enforcement. S3 credentials are never returned by the API.

Artifact download/signing is not part of this slice. Later read access must be per-artifact, short-lived and authorized by dataset/job scope; agents do not receive bucket credentials.

## Next work

After this control API is proven against the real development PostgreSQL and Backblaze configuration, the next ingestion step is connector execution: SCJ Principales first, then SCJ structured decisions 1994+, writing discoveries into `source_documents` and letting this API control which collections are actually acquired.
