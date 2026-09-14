# Source drift recovery and object storage

## Acquisition policy

Official legal-document acquisition is deterministic by default. The normal path must never require an LLM or browser agent:

1. fetch an allowlisted official URL;
2. validate the expected source-surface contract;
3. discover document links deterministically;
4. download and validate PDF bytes;
5. hash with SHA-256;
6. store under a content-addressed object key;
7. checkpoint the successful acquisition.

## Source drift

A source surface is considered drifted when its deterministic contract no longer holds. Examples include the disappearance of expected legal-document links, required page markers, or a changed navigation surface that causes deterministic discovery to fail.

The scheduled `Official source probe` runs independently of mass acquisition. When drift is detected it:

- fails closed with `SOURCE_DRIFT`;
- preserves the fetched HTML and observation metadata;
- emits a `browser-recovery-*.json` request;
- does not silently alter selectors, endpoints, or download rules.

A browser-capable recovery agent may then use Playwright to inspect the official site, collect DOM/network/screenshot evidence, and propose a revised deterministic source contract. Any proposed contract change must be committed and pass CI before it becomes part of production acquisition.

This keeps the LLM/browser agent in a diagnostic role rather than making legal provenance depend on autonomous browsing behavior.

## Object-storage decision

JurisNexo uses its own narrow `ObjectStore` boundary for corpus behavior and **boto3 as the S3 protocol SDK** at the infrastructure edge.

This is intentional. We do not add a provider SDK for every object-storage vendor and we do not use a filesystem abstraction such as `s3fs` as the canonical storage contract. The application needs S3 object semantics such as `HeadObject`, `PutObject`, object metadata, deterministic keys and later signed-object operations; pretending an object store is a POSIX filesystem would not simplify those guarantees.

The same boto3-based runtime is intended to work with:

- AWS S3;
- Supabase Storage through its S3-compatible endpoint;
- Cloudflare R2;
- Backblaze B2 S3-compatible storage;
- MinIO;
- another service that implements the S3 operations JurisNexo actually uses.

Provider compatibility must be judged by the operations JurisNexo requires, not by a vendor claiming complete S3 parity.

## Central runtime configuration

S3-enabled jobs load one typed configuration through `S3RuntimeSettings` and create clients through the shared factory in `jurisnexo.acquisition.s3_object_store`.

Required configuration:

```text
JURISNEXO_S3_BUCKET=jurisnexo-official
JURISNEXO_S3_REGION=<provider region; use the provider-specific value such as auto for R2>
```

Optional custom endpoint:

```text
JURISNEXO_S3_ENDPOINT_URL=https://<provider S3 endpoint>
```

If `JURISNEXO_S3_ENDPOINT_URL` is omitted, boto3 resolves the native AWS S3 endpoint for the configured region. This permits AWS deployment without manufacturing a custom endpoint URL.

Addressing style is configurable:

```text
JURISNEXO_S3_FORCE_PATH_STYLE=true
```

The default remains path-style for backward compatibility with the current Supabase deployment. Set it to `false` for providers or deployments that require or prefer virtual-host addressing.

## Credentials

JurisNexo supports two credential modes.

### Explicit provider credentials

For Supabase, R2, B2 and similar S3-compatible services, deployment configuration may supply:

```text
JURISNEXO_S3_ACCESS_KEY_ID=<secret>
JURISNEXO_S3_SECRET_ACCESS_KEY=<secret>
JURISNEXO_S3_SESSION_TOKEN=<optional temporary token>
```

The access key and secret key must be provided together. A session token is accepted only with that explicit pair.

### Boto3 credential-provider chain

If the JurisNexo-specific access key and secret key are both omitted, the shared factory deliberately does **not** pass credential arguments to boto3. Boto3 may then use its standard credential-provider chain, including AWS environment variables, shared profiles, web-identity/assume-role configuration, container credentials and instance-role credentials where the deployment supports them.

This is the preferred path for AWS-hosted production because it avoids forcing long-lived static AWS credentials into JurisNexo configuration.

Secrets must be supplied by the deployment environment, workload identity or secret manager and must never be committed to the repository.

## Transport, retries and connection behavior

HTTPS is required by default.

A local MinIO development deployment may opt into plain HTTP explicitly with:

```text
JURISNEXO_S3_ALLOW_INSECURE_HTTP=true
JURISNEXO_S3_ENDPOINT_URL=http://minio:9000
```

That flag exists for controlled local development only. Production object storage should remain TLS-protected.

The shared boto3 client also owns the common S3 transport policy instead of duplicating it in each job:

```text
JURISNEXO_S3_CONNECT_TIMEOUT_SECONDS=5
JURISNEXO_S3_READ_TIMEOUT_SECONDS=60
JURISNEXO_S3_MAX_ATTEMPTS=4
JURISNEXO_S3_MAX_POOL_CONNECTIONS=32
```

The client uses AWS Signature Version 4 and boto3/botocore standard retry behavior. These values may be tuned from deployment configuration without changing acquisition code.

## Integrity and portability

Object identity is provider-neutral and content-addressed. Current official-corpus keys follow the jurisdiction/source/collection namespace, for example:

```text
jurisdictions/do/scj/decisions/{sha256[0:2]}/{sha256}.pdf
jurisdictions/do/scj/bulletins/{sha256[0:2]}/{sha256}.pdf
jurisdictions/do/tc/decisions/{sha256[0:2]}/{sha256}.pdf
```

The SHA-256 digest, source URL, source identifier, byte count, acquisition manifest and corpus provenance remain authoritative even if the underlying S3 provider changes.

Bucket versioning is not assumed. JurisNexo detects changed content by digest and preserves new bytes under a new content-addressed key rather than overwriting canonical historical evidence.

## Production connectivity smoke

The full official-corpus workflow validates the configured object store before database validation, inventory work or mass acquisition. The smoke probe exercises only the S3 operations required by the current corpus storage path:

```text
PutObject
HeadObject
ListObjectsV2
```

Operational probes are isolated from legal evidence under a reserved namespace:

```text
_system/smoke-tests/<run-id>.txt
```

They must never be written beneath `jurisdictions/`. The probe attempts `DeleteObject` only as best-effort cleanup; delete permission is not part of the current corpus write/read contract and a cleanup denial does not make an otherwise valid storage probe fail.

The workflow exposes a manual `s3-smoke` scope so production S3 credentials and provider compatibility can be checked without starting the SCJ or TC backfill. The normal `full` scope runs the same storage probe before continuing. The bucket name itself is deployment configuration and is not required to be `official-corpus` or any other hard-coded value.

## Current scope and limits

The generic S3 runtime is implemented for official-corpus acquisition and verification. It does **not** yet mean that every future product storage concern is finished.

Private tenant uploads, report exports, presigned upload/download URLs, lifecycle policies, multipart thresholds, encryption policy and tenant-specific authorization still require their own product contracts before they are treated as implemented capabilities. Those features should reuse the same provider-neutral S3 infrastructure where appropriate rather than bypassing it with vendor-specific application logic.
