from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    RecoveryCheckpointRecord,
    S3RecoveryCheckpointMirror,
    classify_infrastructure_error,
    utc_now_z,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


class FakeS3Error(RuntimeError):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


def _stored() -> RecoveryCheckpointRecord:
    return RecoveryCheckpointRecord(
        source_identifier="decision-1",
        document_url="https://official.example/1.pdf",
        status="stored",
        recorded_at=utc_now_z(),
        sha256="a" * 64,
        object_key="jurisdictions/do/scj/decisions/aa/" + ("a" * 64) + ".pdf",
        byte_count=123,
        content_type="application/pdf",
        file_extension="pdf",
    )


def test_journal_is_durable_and_latest_record_wins(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    first = _stored()
    journal = AcquisitionRecoveryJournal(path)
    journal.append(first)
    journal.append(
        RecoveryCheckpointRecord(
            source_identifier=first.source_identifier,
            document_url=first.document_url,
            status="failed",
            recorded_at=utc_now_z(),
            error_type="RuntimeError",
            reason="later observation",
        )
    )

    restored = AcquisitionRecoveryJournal(path)
    record = restored.get(
        source_identifier=first.source_identifier,
        document_url=first.document_url,
    )
    assert record is not None
    assert record.status == "failed"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (
            FakeS3Error("QuotaExceeded", 400, "storage quota exceeded"),
            "storage_capacity_exceeded",
            False,
        ),
        (
            FakeS3Error("StorageCapExceeded", 403, "storage cap exceeded for account"),
            "storage_capacity_exceeded",
            False,
        ),
        (FakeS3Error("AccessDenied", 403, "no"), "authorization_error", False),
        (FakeS3Error("NoSuchBucket", 404, "missing"), "bucket_configuration_error", False),
        (FakeS3Error("SlowDown", 429, "slow down"), "rate_limited", True),
        (FakeS3Error("ServiceUnavailable", 503, "later"), "storage_unavailable", True),
        (
            RuntimeError(
                "Connection was closed before we received a valid response from endpoint URL"
            ),
            "transport_error",
            True,
        ),
    ],
)
def test_infrastructure_failures_are_classified(
    error: Exception,
    kind: str,
    retryable: bool,
) -> None:
    failure = classify_infrastructure_error(error)
    assert failure is not None
    assert failure.kind == kind
    assert failure.retryable is retryable


def test_document_error_is_not_misclassified_as_global_infrastructure() -> None:
    assert classify_infrastructure_error(ValueError("official document is not supported")) is None


def test_backblaze_capacity_incident_preserves_completed_work_for_resume(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recovery-checkpoint.jsonl"
    journal = AcquisitionRecoveryJournal(path)
    first = _stored()
    second = RecoveryCheckpointRecord(
        source_identifier="decision-2",
        document_url="https://official.example/2.pdf",
        status="stored",
        recorded_at=utc_now_z(),
        sha256="b" * 64,
        object_key="jurisdictions/do/scj/decisions/bb/" + ("b" * 64) + ".pdf",
        byte_count=456,
        content_type="application/pdf",
        file_extension="pdf",
    )
    journal.append(first)
    journal.append(second)

    failure = classify_infrastructure_error(
        FakeS3Error("QuotaExceeded", 400, "storage quota exceeded")
    )
    assert failure is not None
    assert failure.kind == "storage_capacity_exceeded"
    assert failure.retryable is False

    restored = AcquisitionRecoveryJournal(path)
    assert restored.get(
        source_identifier=first.source_identifier,
        document_url=first.document_url,
    ) == first
    assert restored.get(
        source_identifier=second.source_identifier,
        document_url=second.document_url,
    ) == second
    assert restored.get(
        source_identifier="decision-3",
        document_url="https://official.example/3.pdf",
    ) is None



class FakeCheckpointClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: dict[str, str],
        **_: object,
    ) -> None:
        assert Bucket == "checkpoint-bucket"
        self.objects[Key] = Body
        self.metadata[Key] = dict(Metadata)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == "checkpoint-bucket"
        if Key not in self.objects:
            error = FakeS3Error("NoSuchKey", 404, "missing")
            raise error
        return {
            "Body": BytesIO(self.objects[Key]),
            "Metadata": self.metadata.get(Key, {}),
        }


class FakeCheckpointConfig:
    bucket = "checkpoint-bucket"


class FakeCheckpointStore:
    def __init__(self) -> None:
        self.client = FakeCheckpointClient()
        self.config = FakeCheckpointConfig()

    @staticmethod
    def is_not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        return response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404


def test_remote_checkpoint_mirror_survives_loss_of_runner_disk(tmp_path: Path) -> None:
    store = FakeCheckpointStore()
    first_path = tmp_path / "runner-a.jsonl"
    first = AcquisitionRecoveryJournal(first_path)
    record = _stored()
    first.append(record)
    mirror = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key="_checkpoints/scj/decisions/snapshot-a/shard-000.jsonl",
        checkpoint_identity="scj:decisions:snapshot-a:0:1",
    )
    mirror.persist(first)

    first_path.unlink()
    restored = AcquisitionRecoveryJournal(tmp_path / "runner-b.jsonl")
    assert mirror.load_if_present(restored) is True
    assert restored.get(
        source_identifier="decision-1",
        document_url="https://official.example/1.pdf",
    ) == record


def test_remote_checkpoint_missing_is_not_an_error(tmp_path: Path) -> None:
    store = FakeCheckpointStore()
    mirror = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key="_checkpoints/scj/decisions/snapshot-a/shard-001.jsonl",
        checkpoint_identity="scj:decisions:snapshot-a:1:2",
    )
    journal = AcquisitionRecoveryJournal(tmp_path / "checkpoint.jsonl")
    assert mirror.load_if_present(journal) is False


def test_remote_checkpoint_rejects_corrupted_payload(tmp_path: Path) -> None:
    store = FakeCheckpointStore()
    journal = AcquisitionRecoveryJournal(tmp_path / "runner-a.jsonl")
    journal.append(_stored())
    mirror = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key="_checkpoints/scj/decisions/snapshot-a/shard-000.jsonl",
        checkpoint_identity="scj:decisions:snapshot-a:0:1",
    )
    mirror.persist(journal)
    store.client.objects[mirror.object_key] += b"corruption"

    restored = AcquisitionRecoveryJournal(tmp_path / "runner-b.jsonl")
    with pytest.raises(RuntimeError, match="CHECKPOINT_INTEGRITY_MISMATCH"):
        mirror.load_if_present(restored)


def test_remote_checkpoint_rejects_identity_mismatch(tmp_path: Path) -> None:
    store = FakeCheckpointStore()
    journal = AcquisitionRecoveryJournal(tmp_path / "runner-a.jsonl")
    journal.append(_stored())
    writer = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key="_checkpoints/scj/decisions/snapshot-a/shard-000.jsonl",
        checkpoint_identity="scj:decisions:snapshot-a:0:1",
    )
    writer.persist(journal)

    reader = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key=writer.object_key,
        checkpoint_identity="scj:decisions:snapshot-b:0:1",
    )
    restored = AcquisitionRecoveryJournal(tmp_path / "runner-b.jsonl")
    with pytest.raises(RuntimeError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        reader.load_if_present(restored)
