from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from jurisnexo.acquisition.official_corpus import (
    ArtifactCatalog,
    HttpFetcher,
    ObjectStore,
    OfficialDocumentCandidate,
    SourceName,
    StoredOfficialArtifact,
    acquire_candidates,
)

_RUN_SCHEMA_VERSION = 3
_STORAGE_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RunItemStatus = Literal["uploaded", "already_present", "failed", "unavailable"]
VerificationMethod = Literal["downloaded_and_hashed", "prior_manifest_and_head"]
RunStatus = Literal["succeeded", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class AcquisitionManifestRecord:
    source: SourceName
    source_identifier: str
    discovery_url: str
    document_url: str
    sha256: str
    byte_count: int
    object_key: str
    content_type: str = "application/pdf"
    file_extension: str = "pdf"

    def to_artifact(self, candidate: OfficialDocumentCandidate) -> StoredOfficialArtifact:
        return StoredOfficialArtifact(
            candidate=candidate,
            sha256=self.sha256,
            byte_count=self.byte_count,
            object_key=self.object_key,
            already_present=True,
            content_type=self.content_type,
            file_extension=self.file_extension,
        )


class FileAcquisitionManifest:
    """Append-only local checkpoint used to resume deterministic acquisition."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[tuple[SourceName, str], AcquisitionManifestRecord] = {}
        if path.exists():
            self._load()

    @staticmethod
    def _key(source: SourceName, document_url: str) -> tuple[SourceName, str]:
        return source, document_url

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = AcquisitionManifestRecord(**payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid acquisition manifest record at line {line_number}"
                ) from exc
            self._records[self._key(record.source, record.document_url)] = record

    def get(self, candidate: OfficialDocumentCandidate) -> AcquisitionManifestRecord | None:
        return self._records.get(self._key(candidate.source, candidate.document_url))

    def append(self, artifact: StoredOfficialArtifact) -> None:
        record = AcquisitionManifestRecord(
            source=artifact.candidate.source,
            source_identifier=artifact.candidate.source_identifier,
            discovery_url=artifact.candidate.discovery_url,
            document_url=artifact.candidate.document_url,
            sha256=artifact.sha256,
            byte_count=artifact.byte_count,
            object_key=artifact.object_key,
            content_type=artifact.content_type,
            file_extension=artifact.file_extension,
        )
        key = self._key(record.source, record.document_url)
        existing = self._records.get(key)
        if existing == record:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
        self._records[key] = record


@dataclass(frozen=True, slots=True)
class AcquisitionRunItem:
    collection: str
    source_identifier: str
    discovery_url: str
    document_url: str | None
    status: RunItemStatus
    sha256: str | None = None
    byte_count: int | None = None
    object_key: str | None = None
    content_type: str | None = None
    file_extension: str | None = None
    verification_method: VerificationMethod | None = None
    error_type: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not _STORAGE_SEGMENT_RE.fullmatch(self.collection):
            raise ValueError("collection must be a lowercase kebab-case storage segment")
        if not self.source_identifier.strip():
            raise ValueError("source_identifier must not be empty")
        if not self.discovery_url.strip():
            raise ValueError("discovery_url must not be empty")
        if self.byte_count is not None and self.byte_count < 0:
            raise ValueError("byte_count must not be negative")

        if self.status in {"uploaded", "already_present"}:
            if not self.document_url:
                raise ValueError("stored run items require document_url")
            if self.sha256 is None or len(self.sha256) != 64:
                raise ValueError("stored run items require a SHA-256 digest")
            if self.object_key is None:
                raise ValueError("stored run items require object_key")
            if self.content_type is None or not self.content_type.strip():
                raise ValueError("stored run items require content_type")
            if self.file_extension not in {"pdf", "doc", "docx", "rtf"}:
                raise ValueError("stored run items require a supported file_extension")
            if self.verification_method is None:
                raise ValueError("stored run items require verification_method")
        elif (
            self.sha256 is not None
            or self.object_key is not None
            or self.content_type is not None
            or self.file_extension is not None
            or self.verification_method is not None
        ):
            raise ValueError("failed/unavailable run items cannot claim a stored artifact")


@dataclass(frozen=True, slots=True)
class AcquisitionRunManifest:
    schema_version: int
    ingestion_id: str
    batch_id: str
    partition_index: int
    partition_count: int
    source: str
    scope: str
    storage_bucket: str
    started_at: str
    completed_at: str
    status: RunStatus
    discovered_count: int
    uploaded_count: int
    already_present_count: int
    unavailable_count: int
    failed_count: int
    source_inventory_sha256: str
    artifact_set_sha256: str
    certified_inventory_sha256: str | None
    items: tuple[AcquisitionRunItem, ...]

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


def parse_acquisition_run_manifest(payload: bytes) -> AcquisitionRunManifest:
    """Parse and validate a canonical acquisition run manifest.

    Invalid JSON, unknown/missing fields, invalid run items, or unsupported
    schema versions fail closed instead of being tolerated by normalization.
    """

    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid acquisition run manifest JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("acquisition run manifest root must be an object")
    schema_version = raw.get("schema_version")
    if schema_version != _RUN_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported acquisition run manifest schema_version={schema_version!r}"
        )
    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise ValueError("acquisition run manifest items must be an array")
    try:
        items = tuple(
            AcquisitionRunItem(**item)
            for item in items_raw
            if isinstance(item, dict)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid acquisition run manifest item") from exc
    if len(items) != len(items_raw):
        raise ValueError("acquisition run manifest items must be objects")
    manifest_raw = dict(raw)
    manifest_raw["items"] = items
    try:
        manifest = AcquisitionRunManifest(**manifest_raw)
    except TypeError as exc:
        raise ValueError("invalid acquisition run manifest shape") from exc

    if manifest.discovered_count != len(manifest.items):
        raise ValueError("acquisition run manifest discovered_count does not match items")
    counts = {
        "uploaded": sum(item.status == "uploaded" for item in manifest.items),
        "already_present": sum(
            item.status == "already_present" for item in manifest.items
        ),
        "unavailable": sum(item.status == "unavailable" for item in manifest.items),
        "failed": sum(item.status == "failed" for item in manifest.items),
    }
    declared = {
        "uploaded": manifest.uploaded_count,
        "already_present": manifest.already_present_count,
        "unavailable": manifest.unavailable_count,
        "failed": manifest.failed_count,
    }
    if counts != declared:
        raise ValueError("acquisition run manifest status counts do not match items")
    canonical = manifest.canonical_bytes()
    if hashlib.sha256(canonical).digest() != hashlib.sha256(payload).digest():
        # The semantic manifest is valid, but normalization identity must use the
        # exact immutable bytes stored by acquisition. Non-canonical encodings
        # are rejected so hashes cannot silently drift across equivalent JSON.
        raise ValueError("acquisition run manifest is not canonical JSON")
    return manifest


@dataclass(frozen=True, slots=True)
class StoredAcquisitionRunManifest:
    manifest: AcquisitionRunManifest
    object_key: str
    payload_sha256: str
    byte_count: int


class AcquisitionRunManifestBuilder:
    """Collect one acquisition run and commit it as one immutable storage record."""

    def __init__(
        self,
        *,
        source: str,
        scope: str,
        storage_bucket: str,
        ingestion_id: str | None = None,
        batch_id: str | None = None,
        partition_index: int = 0,
        partition_count: int = 1,
        certified_inventory_sha256: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        if not _STORAGE_SEGMENT_RE.fullmatch(source):
            raise ValueError("source must be a lowercase kebab-case storage segment")
        if not _STORAGE_SEGMENT_RE.fullmatch(scope):
            raise ValueError("scope must be a lowercase kebab-case storage segment")
        if not storage_bucket.strip():
            raise ValueError("storage_bucket must not be empty")
        if partition_count < 1:
            raise ValueError("partition_count must be at least 1")
        if not 0 <= partition_index < partition_count:
            raise ValueError("partition_index must be within partition_count")
        self.source = source
        self.scope = scope
        self.storage_bucket = storage_bucket.strip()
        self.ingestion_id = ingestion_id or str(uuid.uuid4())
        self.batch_id = batch_id or self.ingestion_id
        for field_name, value in (
            ("ingestion_id", self.ingestion_id),
            ("batch_id", self.batch_id),
        ):
            if "/" in value or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty object-key-safe identifier")
        if certified_inventory_sha256 is not None and len(certified_inventory_sha256) != 64:
            raise ValueError("certified_inventory_sha256 must be a SHA-256 digest")
        self.partition_index = partition_index
        self.partition_count = partition_count
        self.certified_inventory_sha256 = certified_inventory_sha256
        self.started_at = _utc(started_at or datetime.now(UTC))
        self._items: dict[tuple[str, str, str], AcquisitionRunItem] = {}
        self._committed = False

    def record_artifact(self, artifact: StoredOfficialArtifact) -> None:
        self._record(
            AcquisitionRunItem(
                collection=artifact.candidate.collection,
                source_identifier=artifact.candidate.source_identifier,
                discovery_url=artifact.candidate.discovery_url,
                document_url=artifact.candidate.document_url,
                status="already_present" if artifact.already_present else "uploaded",
                sha256=artifact.sha256,
                byte_count=artifact.byte_count,
                object_key=artifact.object_key,
                content_type=artifact.content_type,
                file_extension=artifact.file_extension,
                verification_method="downloaded_and_hashed",
            )
        )

    def record_existing(
        self,
        *,
        candidate: OfficialDocumentCandidate,
        sha256: str,
        object_key: str,
        byte_count: int | None = None,
        content_type: str = "application/pdf",
        file_extension: str = "pdf",
    ) -> None:
        self._record(
            AcquisitionRunItem(
                collection=candidate.collection,
                source_identifier=candidate.source_identifier,
                discovery_url=candidate.discovery_url,
                document_url=candidate.document_url,
                status="already_present",
                sha256=sha256,
                byte_count=byte_count,
                object_key=object_key,
                content_type=content_type,
                file_extension=file_extension,
                verification_method="prior_manifest_and_head",
            )
        )

    def record_failure(
        self,
        *,
        collection: str,
        source_identifier: str,
        discovery_url: str,
        document_url: str | None,
        error: Exception,
    ) -> None:
        self._record(
            AcquisitionRunItem(
                collection=collection,
                source_identifier=source_identifier,
                discovery_url=discovery_url,
                document_url=document_url,
                status="failed",
                error_type=type(error).__name__,
                error=str(error)[:2000],
            )
        )

    def record_unavailable(
        self,
        *,
        collection: str,
        source_identifier: str,
        discovery_url: str,
        document_url: str | None = None,
        error_type: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._record(
            AcquisitionRunItem(
                collection=collection,
                source_identifier=source_identifier,
                discovery_url=discovery_url,
                document_url=document_url,
                status="unavailable",
                error_type=error_type,
                error=reason[:2000] if reason else None,
            )
        )

    def _record(self, item: AcquisitionRunItem) -> None:
        if self._committed:
            raise RuntimeError("acquisition run manifest is already committed")
        key = (item.collection, item.source_identifier, item.document_url or item.discovery_url)
        self._items[key] = item

    def build(self, *, completed_at: datetime | None = None) -> AcquisitionRunManifest:
        if self._committed:
            raise RuntimeError("acquisition run manifest is already committed")
        completed = _utc(completed_at or datetime.now(UTC))
        if completed < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        items = tuple(sorted(self._items.values(), key=_item_sort_key))
        uploaded = sum(item.status == "uploaded" for item in items)
        already_present = sum(item.status == "already_present" for item in items)
        unavailable = sum(item.status == "unavailable" for item in items)
        failed = sum(item.status == "failed" for item in items)
        successful = uploaded + already_present
        status: RunStatus
        if failed == 0:
            status = "succeeded"
        elif successful == 0:
            status = "failed"
        else:
            status = "partial"

        return AcquisitionRunManifest(
            schema_version=_RUN_SCHEMA_VERSION,
            ingestion_id=self.ingestion_id,
            batch_id=self.batch_id,
            partition_index=self.partition_index,
            partition_count=self.partition_count,
            source=self.source,
            scope=self.scope,
            storage_bucket=self.storage_bucket,
            started_at=_iso_z(self.started_at),
            completed_at=_iso_z(completed),
            status=status,
            discovered_count=len(items),
            uploaded_count=uploaded,
            already_present_count=already_present,
            unavailable_count=unavailable,
            failed_count=failed,
            source_inventory_sha256=_inventory_digest(items),
            artifact_set_sha256=_artifact_set_digest(items),
            certified_inventory_sha256=self.certified_inventory_sha256,
            items=items,
        )

    def commit(
        self,
        *,
        object_store: ObjectStore,
        completed_at: datetime | None = None,
    ) -> StoredAcquisitionRunManifest:
        manifest = self.build(completed_at=completed_at)
        payload = manifest.canonical_bytes()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        completed = datetime.fromisoformat(manifest.completed_at.replace("Z", "+00:00"))
        key = run_manifest_object_key(
            source=self.source,
            scope=self.scope,
            ingestion_id=self.ingestion_id,
            completed_at=completed,
        )
        if object_store.exists(key):
            raise FileExistsError(f"refusing to overwrite acquisition run manifest: {key}")
        object_store.put(
            key=key,
            content=payload,
            content_type="application/json",
            metadata={
                "schema_version": str(_RUN_SCHEMA_VERSION),
                "ingestion_id": self.ingestion_id,
                "source": self.source,
                "scope": self.scope,
                "storage_bucket": self.storage_bucket,
                "batch_id": self.batch_id,
                "partition_index": str(self.partition_index),
                "partition_count": str(self.partition_count),
                "status": manifest.status,
                "payload_sha256": payload_sha256,
                **(
                    {"certified_inventory_sha256": self.certified_inventory_sha256}
                    if self.certified_inventory_sha256
                    else {}
                ),
            },
        )
        self._committed = True
        return StoredAcquisitionRunManifest(
            manifest=manifest,
            object_key=key,
            payload_sha256=payload_sha256,
            byte_count=len(payload),
        )


def run_manifest_object_key(
    *,
    source: str,
    scope: str,
    ingestion_id: str,
    completed_at: datetime,
) -> str:
    if not _STORAGE_SEGMENT_RE.fullmatch(source):
        raise ValueError("source must be a lowercase kebab-case storage segment")
    if not _STORAGE_SEGMENT_RE.fullmatch(scope):
        raise ValueError("scope must be a lowercase kebab-case storage segment")
    if "/" in ingestion_id or not ingestion_id.strip():
        raise ValueError("ingestion_id must be a non-empty object-key-safe identifier")
    completed = _utc(completed_at)
    return (
        f"_manifests/{source}/{scope}/{completed:%Y/%m/%d}/"
        f"{ingestion_id}.json"
    )


def acquire_candidates_resumable(
    *,
    candidates: tuple[OfficialDocumentCandidate, ...],
    fetcher: HttpFetcher,
    object_store: ObjectStore,
    manifest: FileAcquisitionManifest,
    artifact_catalog: ArtifactCatalog | None = None,
    refresh: bool = False,
) -> tuple[StoredOfficialArtifact, ...]:
    """Acquire candidates and preserve every successful URL-to-content observation."""

    results: list[StoredOfficialArtifact] = []
    seen_urls: set[tuple[SourceName, str]] = set()
    for candidate in candidates:
        key = (candidate.source, candidate.document_url)
        if key in seen_urls:
            continue
        seen_urls.add(key)

        existing = manifest.get(candidate)
        if existing is not None and not refresh:
            artifact = existing.to_artifact(candidate)
            if artifact_catalog is not None:
                artifact_catalog.register(artifact)
            results.append(artifact)
            continue

        acquired = acquire_candidates(
            candidates=(candidate,),
            fetcher=fetcher,
            object_store=object_store,
            artifact_catalog=artifact_catalog,
        )[0]
        manifest.append(acquired)
        results.append(acquired)
    return tuple(results)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("manifest timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _item_sort_key(item: AcquisitionRunItem) -> tuple[str, str, str, str]:
    return (
        item.collection,
        item.source_identifier,
        item.document_url or "",
        item.discovery_url,
    )


def _inventory_digest(items: tuple[AcquisitionRunItem, ...]) -> str:
    observations = [
        {
            "collection": item.collection,
            "source_identifier": item.source_identifier,
            "discovery_url": item.discovery_url,
            "document_url": item.document_url,
        }
        for item in items
    ]
    payload = json.dumps(
        observations,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact_set_digest(items: tuple[AcquisitionRunItem, ...]) -> str:
    artifacts = [
        {
            "collection": item.collection,
            "source_identifier": item.source_identifier,
            "sha256": item.sha256,
            "object_key": item.object_key,
            "content_type": item.content_type,
            "file_extension": item.file_extension,
        }
        for item in items
        if item.status in {"uploaded", "already_present"}
    ]
    payload = json.dumps(
        artifacts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
