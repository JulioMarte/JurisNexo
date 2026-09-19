from __future__ import annotations

from pathlib import Path

import pytest

from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    RecoveryCheckpointRecord,
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
        (FakeS3Error("QuotaExceeded", 400, "storage quota exceeded"), "storage_capacity_exceeded", False),
        (FakeS3Error("AccessDenied", 403, "no"), "authorization_error", False),
        (FakeS3Error("NoSuchBucket", 404, "missing"), "bucket_configuration_error", False),
        (FakeS3Error("SlowDown", 429, "slow down"), "rate_limited", True),
        (FakeS3Error("ServiceUnavailable", 503, "later"), "storage_unavailable", True),
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
