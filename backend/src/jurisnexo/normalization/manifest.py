from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from jurisnexo.acquisition.official_corpus import ObjectStore
from jurisnexo.normalization.reconciliation import ReconciliationReport


@dataclass(frozen=True, slots=True)
class NormalizationManifestItem:
    source_artifact_id: str
    status: str
    normalized_artifact_id: str | None
    quality_state: str


@dataclass(frozen=True, slots=True)
class NormalizationManifest:
    schema_version: int
    run_id: str
    pipeline_version: str
    config_sha256: str
    input_manifest_sha256: str
    published_at: str
    selected_count: int
    normalized_count: int
    review_required_count: int
    failed_count: int
    skipped_count: int
    items: tuple[NormalizationManifestItem, ...]

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                asdict(self),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class StoredNormalizationManifest:
    manifest: NormalizationManifest
    object_key: str
    sha256: str
    byte_count: int


def build_normalization_manifest(
    *,
    run_id: str,
    pipeline_version: str,
    config_sha256: str,
    input_manifest_sha256: str,
    items: tuple[NormalizationManifestItem, ...],
    reconciliation: ReconciliationReport,
    published_at: datetime | None = None,
) -> NormalizationManifest:
    if not reconciliation.can_close:
        raise ValueError("normalization run cannot publish a manifest before reconciliation")
    if len(config_sha256) != 64 or len(input_manifest_sha256) != 64:
        raise ValueError("manifest digests must be SHA-256 values")
    ordered = tuple(sorted(items, key=lambda item: item.source_artifact_id))
    return NormalizationManifest(
        schema_version=1,
        run_id=run_id,
        pipeline_version=pipeline_version,
        config_sha256=config_sha256,
        input_manifest_sha256=input_manifest_sha256,
        published_at=(published_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        selected_count=len(ordered),
        normalized_count=sum(item.status == "normalized" for item in ordered),
        review_required_count=sum(
            item.status == "quality_review_required" for item in ordered
        ),
        failed_count=sum(item.status == "failed" for item in ordered),
        skipped_count=sum(item.status == "skipped" for item in ordered),
        items=ordered,
    )


def publish_normalization_manifest(
    *, object_store: ObjectStore, manifest: NormalizationManifest
) -> StoredNormalizationManifest:
    payload = manifest.canonical_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    key = f"_manifests/normalization/{manifest.run_id}/{digest}.json"
    if object_store.exists(key):
        return StoredNormalizationManifest(manifest, key, digest, len(payload))
    object_store.put(
        key=key,
        content=payload,
        content_type="application/json",
        metadata={
            "sha256": digest,
            "schema_version": str(manifest.schema_version),
            "run_id": manifest.run_id,
            "pipeline_version": manifest.pipeline_version,
        },
    )
    return StoredNormalizationManifest(manifest, key, digest, len(payload))
