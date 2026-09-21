from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jurisnexo.acquisition.official_corpus import ObjectStore


@dataclass(frozen=True, slots=True)
class StoredDerivedArtifact:
    sha256: str
    byte_count: int
    object_key: str
    content_type: str
    artifact_kind: str
    already_present: bool


def derived_object_key(
    *, artifact_kind: str, pipeline_version: str, sha256: str
) -> str:
    if not artifact_kind.strip() or "/" in artifact_kind:
        raise ValueError("artifact_kind must be a non-empty path-safe segment")
    if not pipeline_version.strip() or "/" in pipeline_version:
        raise ValueError("pipeline_version must be a non-empty path-safe segment")
    if len(sha256) != 64:
        raise ValueError("sha256 must be a SHA-256 digest")
    return f"derived/normalization/{artifact_kind}/{pipeline_version}/{sha256}"


def store_derived_artifact(
    *,
    object_store: ObjectStore,
    payload: bytes,
    content_type: str,
    artifact_kind: str,
    pipeline_version: str,
    metadata: dict[str, str] | None = None,
) -> StoredDerivedArtifact:
    digest = hashlib.sha256(payload).hexdigest()
    key = derived_object_key(
        artifact_kind=artifact_kind,
        pipeline_version=pipeline_version,
        sha256=digest,
    )
    if object_store.exists(key):
        return StoredDerivedArtifact(
            sha256=digest,
            byte_count=len(payload),
            object_key=key,
            content_type=content_type,
            artifact_kind=artifact_kind,
            already_present=True,
        )
    object_store.put(
        key=key,
        content=payload,
        content_type=content_type,
        metadata={
            "sha256": digest,
            "artifact_kind": artifact_kind,
            "pipeline_version": pipeline_version,
            **(metadata or {}),
        },
    )
    return StoredDerivedArtifact(
        sha256=digest,
        byte_count=len(payload),
        object_key=key,
        content_type=content_type,
        artifact_kind=artifact_kind,
        already_present=False,
    )
