from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pytest

from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    acquire_candidates,
)
from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    RecoveryCheckpointRecord,
    S3RecoveryCheckpointMirror,
    classify_infrastructure_error,
    utc_now_z,
)

pytestmark = [pytest.mark.integration, pytest.mark.provenance]


class FakeS3Error(RuntimeError):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


@dataclass(slots=True)
class FakeConfig:
    bucket: str = "official-corpus"


@dataclass(slots=True)
class FakeFetcher:
    payloads: dict[str, bytes]

    def get_bytes(self, url: str) -> bytes:
        return self.payloads[url]


@dataclass(slots=True)
class FakeS3Client:
    owner: RecoverableMemoryStore

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> None:
        assert Bucket == self.owner.config.bucket
        payload = bytes(Body)
        self.owner.objects[Key] = payload
        self.owner.metadata[Key] = dict(Metadata)
        self.owner.content_types[Key] = ContentType

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == self.owner.config.bucket
        if Key not in self.owner.objects:
            raise FakeS3Error("NoSuchKey", 404, "missing")
        return {"Body": BytesIO(self.owner.objects[Key])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == self.owner.config.bucket
        if Key not in self.owner.objects:
            raise FakeS3Error("NoSuchKey", 404, "missing")
        return {
            "ContentLength": len(self.owner.objects[Key]),
            "Metadata": self.owner.metadata.get(Key, {}),
        }


@dataclass(slots=True)
class RecoverableMemoryStore:
    fail_after_legal_objects: int | None = None
    objects: dict[str, bytes] = field(default_factory=dict)
    metadata: dict[str, dict[str, str]] = field(default_factory=dict)
    content_types: dict[str, str] = field(default_factory=dict)
    config: FakeConfig = field(default_factory=FakeConfig)
    client: FakeS3Client = field(init=False)

    def __post_init__(self) -> None:
        self.client = FakeS3Client(self)

    @staticmethod
    def is_not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        return response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes | BinaryIO,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        legal_count = sum(
            existing.startswith("jurisdictions/do/scj/decisions/")
            for existing in self.objects
        )
        if (
            key.startswith("jurisdictions/do/scj/decisions/")
            and self.fail_after_legal_objects is not None
            and legal_count >= self.fail_after_legal_objects
            and key not in self.objects
        ):
            raise FakeS3Error(
                "StorageCapExceeded",
                403,
                "storage cap exceeded for account",
            )
        payload = content if isinstance(content, bytes) else content.read()
        self.objects[key] = payload
        self.metadata[key] = dict(metadata)
        self.content_types[key] = content_type


def _candidate(index: int) -> OfficialDocumentCandidate:
    return OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier=f"decision-{index}",
        discovery_url="https://official.example/list",
        document_url=f"https://official.example/{index}.pdf",
        collection="decisions",
    )


def test_capacity_interruption_resume_manifest_and_reconciliation(tmp_path: Path) -> None:
    candidates = tuple(_candidate(index) for index in range(5))
    fetcher = FakeFetcher(
        {candidate.document_url: f"%PDF document {index}".encode()
         for index, candidate in enumerate(candidates)}
    )
    store = RecoverableMemoryStore(fail_after_legal_objects=2)
    first_journal = AcquisitionRecoveryJournal(tmp_path / "runner-a.jsonl")
    mirror = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key="_checkpoints/scj/decisions/shard-000.jsonl",
    )

    interrupted = False
    for candidate in candidates:
        try:
            artifact = acquire_candidates(
                candidates=(candidate,),
                fetcher=fetcher,
                object_store=store,
            )[0]
        except Exception as exc:
            failure = classify_infrastructure_error(exc)
            assert failure is not None
            assert failure.kind == "storage_capacity_exceeded"
            assert failure.retryable is False
            interrupted = True
            break
        first_journal.append(
            RecoveryCheckpointRecord(
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
                status="stored",
                recorded_at=utc_now_z(),
                sha256=artifact.sha256,
                object_key=artifact.object_key,
                byte_count=artifact.byte_count,
                content_type=artifact.content_type,
                file_extension=artifact.file_extension,
            )
        )
        mirror.persist(first_journal)

    assert interrupted is True
    assert sum(key.startswith("jurisdictions/do/scj/decisions/") for key in store.objects) == 2

    (tmp_path / "runner-a.jsonl").unlink()
    resumed_journal = AcquisitionRecoveryJournal(tmp_path / "runner-b.jsonl")
    assert mirror.load_if_present(resumed_journal) is True

    store.fail_after_legal_objects = None
    builder = AcquisitionRunManifestBuilder(
        source="scj",
        scope="decisions",
        storage_bucket=store.config.bucket,
        ingestion_id="resume-test",
        batch_id="resume-test",
        certified_inventory_sha256="c" * 64,
    )

    for candidate in candidates:
        recovered = resumed_journal.get(
            source_identifier=candidate.source_identifier,
            document_url=candidate.document_url,
        )
        if recovered is not None and recovered.status == "stored":
            assert recovered.object_key is not None
            head = store.client.head_object(
                Bucket=store.config.bucket,
                Key=recovered.object_key,
            )
            assert int(head["ContentLength"]) == recovered.byte_count
            builder.record_existing(
                candidate=candidate,
                sha256=recovered.sha256 or "",
                object_key=recovered.object_key,
                byte_count=recovered.byte_count,
                content_type=recovered.content_type or "application/pdf",
                file_extension=recovered.file_extension or "pdf",
            )
            continue

        artifact = acquire_candidates(
            candidates=(candidate,),
            fetcher=fetcher,
            object_store=store,
        )[0]
        builder.record_artifact(artifact)
        resumed_journal.append(
            RecoveryCheckpointRecord(
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
                status="stored",
                recorded_at=utc_now_z(),
                sha256=artifact.sha256,
                object_key=artifact.object_key,
                byte_count=artifact.byte_count,
                content_type=artifact.content_type,
                file_extension=artifact.file_extension,
            )
        )
        mirror.persist(resumed_journal)

    stored_manifest = builder.commit(object_store=store)
    assert stored_manifest.manifest.status == "succeeded"
    assert stored_manifest.manifest.discovered_count == 5
    assert stored_manifest.manifest.already_present_count == 2
    assert stored_manifest.manifest.uploaded_count == 3

    manifest_keys = {
        item.object_key
        for item in stored_manifest.manifest.items
        if item.object_key is not None
    }
    live_keys = {
        key
        for key in store.objects
        if key.startswith("jurisdictions/do/scj/decisions/")
    }
    assert manifest_keys == live_keys
    assert len(live_keys) == 5
