from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping, cast

CheckpointStatus = Literal["stored", "unavailable", "failed"]
InfrastructureFailureKind = Literal[
    "storage_capacity_exceeded",
    "authentication_error",
    "authorization_error",
    "bucket_configuration_error",
    "rate_limited",
    "storage_unavailable",
    "transport_error",
]


@dataclass(frozen=True, slots=True)
class RecoveryCheckpointRecord:
    source_identifier: str
    document_url: str
    status: CheckpointStatus
    recorded_at: str
    sha256: str | None = None
    object_key: str | None = None
    byte_count: int | None = None
    content_type: str | None = None
    file_extension: str | None = None
    error_type: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.source_identifier.strip():
            raise ValueError("source_identifier must not be empty")
        if not self.document_url.strip():
            raise ValueError("document_url must not be empty")
        if self.status == "stored":
            if self.sha256 is None or len(self.sha256) != 64:
                raise ValueError("stored checkpoint requires sha256")
            if not self.object_key:
                raise ValueError("stored checkpoint requires object_key")
            if self.byte_count is None or self.byte_count < 0:
                raise ValueError("stored checkpoint requires byte_count")
            if not self.content_type or not self.file_extension:
                raise ValueError("stored checkpoint requires detected format")


class AcquisitionRecoveryJournal:
    """Append-only local journal that survives a shard interruption."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._latest: dict[tuple[str, str], RecoveryCheckpointRecord] = {}
        if path.exists():
            self._load()

    @staticmethod
    def _key(source_identifier: str, document_url: str) -> tuple[str, str]:
        return source_identifier, document_url

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = RecoveryCheckpointRecord(**json.loads(line))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid recovery journal record at line {line_number}"
                ) from exc
            self._latest[self._key(record.source_identifier, record.document_url)] = record

    def get(self, *, source_identifier: str, document_url: str) -> RecoveryCheckpointRecord | None:
        return self._latest.get(self._key(source_identifier, document_url))

    def append(self, record: RecoveryCheckpointRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._latest[self._key(record.source_identifier, record.document_url)] = record


@dataclass(frozen=True, slots=True)
class InfrastructureFailure:
    kind: InfrastructureFailureKind
    retryable: bool
    code: str
    http_status: int
    detail: str


class GlobalAcquisitionInterruption(RuntimeError):
    def __init__(self, failure: InfrastructureFailure, original: Exception) -> None:
        super().__init__(f"{failure.kind}: {failure.detail}")
        self.failure = failure
        self.original = original


def utc_now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def classify_infrastructure_error(exc: Exception) -> InfrastructureFailure | None:
    response = _mapping(getattr(exc, "response", None))
    error = _mapping(response.get("Error")) if response is not None else None
    metadata = _mapping(response.get("ResponseMetadata")) if response is not None else None
    code = str((error or {}).get("Code", ""))
    message = str((error or {}).get("Message", "") or str(exc))
    raw_status = (metadata or {}).get("HTTPStatusCode", 0)
    status = raw_status if isinstance(raw_status, int) else 0
    haystack = f"{type(exc).__name__} {code} {message}".lower()

    capacity_markers = (
        "quota",
        "capacity",
        "storage cap",
        "cap exceeded",
        "insufficientstorage",
        "account cap",
    )
    if code in {"QuotaExceeded", "InsufficientStorage", "StorageQuotaExceeded"} or any(
        marker in haystack for marker in capacity_markers
    ):
        return InfrastructureFailure(
            kind="storage_capacity_exceeded",
            retryable=False,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken"} or any(
        marker in haystack for marker in ("invalid access key", "expired token", "signature")
    ):
        return InfrastructureFailure(
            kind="authentication_error",
            retryable=False,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if code in {"AccessDenied", "Forbidden"} or status == 403:
        return InfrastructureFailure(
            kind="authorization_error",
            retryable=False,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if code in {"NoSuchBucket", "InvalidBucketName"}:
        return InfrastructureFailure(
            kind="bucket_configuration_error",
            retryable=False,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if code in {"SlowDown", "TooManyRequests", "Throttling", "ThrottlingException"} or status == 429:
        return InfrastructureFailure(
            kind="rate_limited",
            retryable=True,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if status >= 500 or code in {
        "InternalError",
        "ServiceUnavailable",
        "RequestTimeout",
        "RequestTimeoutException",
    }:
        return InfrastructureFailure(
            kind="storage_unavailable",
            retryable=True,
            code=code,
            http_status=status,
            detail=message[:1000],
        )

    if any(
        marker in haystack
        for marker in ("timeout", "connection reset", "connection aborted", "endpoint connection")
    ):
        return InfrastructureFailure(
            kind="transport_error",
            retryable=True,
            code=code,
            http_status=status,
            detail=message[:1000],
        )
    return None
