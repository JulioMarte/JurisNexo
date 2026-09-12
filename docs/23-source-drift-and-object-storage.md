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

## Object storage

JurisNexo uses the `ObjectStore` boundary in acquisition code. Production storage should use the S3 protocol rather than a provider-specific SDK.

The current target is Supabase Storage through its S3-compatible endpoint. The same adapter is intended to work later with Backblaze B2, Cloudflare R2, AWS S3, MinIO, or another sufficiently compatible S3 service.

Deployment configuration must supply values equivalent to:

```text
JURISNEXO_S3_BUCKET=jurisnexo-official
JURISNEXO_S3_ENDPOINT_URL=<provider S3 endpoint>
JURISNEXO_S3_REGION=<provider region>
JURISNEXO_S3_ACCESS_KEY_ID=<secret>
JURISNEXO_S3_SECRET_ACCESS_KEY=<secret>
JURISNEXO_S3_FORCE_PATH_STYLE=true
```

Secrets must be supplied by the deployment environment or secret manager and must never be committed to the repository.

## Integrity and portability

Object identity is provider-neutral and content-addressed:

```text
official/{source}/{sha256[0:2]}/{sha256}.pdf
```

The SHA-256 digest, source URL, source identifier, byte count, acquisition manifest, and corpus provenance remain authoritative even if the underlying S3 provider changes.

Bucket versioning is not assumed. JurisNexo detects changed content by digest and preserves new bytes under a new content-addressed key rather than overwriting canonical historical evidence.
