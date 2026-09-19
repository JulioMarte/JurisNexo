from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.http_fetcher import (
    BoundedHttpFetcher,
    SCJ_DECISION_DOCUMENT_HOSTS,
)
from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    UnsupportedOfficialDocumentResponse,
    acquire_candidates,
)
from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    GlobalAcquisitionInterruption,
    RecoveryCheckpointRecord,
    classify_infrastructure_error,
    utc_now_z,
)
from jurisnexo.acquisition.s3_object_store import build_s3_object_store

REQUIRED_ENV = (
    "SCJ_1994_INVENTORY_FILE",
    "SCJ_BACKFILL_SHARD_INDEX",
    "SCJ_BACKFILL_SHARD_COUNT",
    "SCJ_BACKFILL_OUTPUT",
)
MAX_ATTEMPTS = int(os.environ.get("SCJ_BACKFILL_ITEM_ATTEMPTS", "3"))


def _event(name: str, **payload: object) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "event": name,
                **payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require_environment() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing SCJ 1994+ backfill configuration: " + ", ".join(missing))


def _batch_id() -> str:
    explicit = os.environ.get("ACQUISITION_BATCH_ID", "").strip()
    if explicit:
        return explicit
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    if run_id and run_attempt:
        return f"github-{run_id}-{run_attempt}-scj-sentencias-1994-actualidad"
    return f"local-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-scj-sentencias-1994-actualidad"


def _load_assigned(
    *,
    path: Path,
    shard_index: int,
    shard_count: int,
) -> list[OfficialDocumentCandidate]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("SCJ acquisition inventory contains a non-object record")
            records.append(record)

    records.sort(
        key=lambda item: (
            int(item["year"]),
            str(item["surface"]),
            str(item["source_identifier"]),
        )
    )
    assigned: list[OfficialDocumentCandidate] = []
    for index, record in enumerate(records):
        if index % shard_count != shard_index:
            continue
        document_url = str(record.get("document_url") or "").strip()
        collection = str(record.get("collection") or "").strip()
        source_identifier = str(record.get("source_identifier") or "").strip()
        discovery_url = str(record.get("discovery_url") or "").strip()
        if not document_url.startswith("https://"):
            raise ValueError("SCJ acquisition record lacks HTTPS document_url")
        if collection != "decisions":
            raise ValueError(
                f"1994+ acquisition unexpectedly contains non-decisions collection: {collection!r}"
            )
        assigned.append(
            OfficialDocumentCandidate(
                source="supreme_court",
                source_identifier=source_identifier,
                discovery_url=discovery_url,
                document_url=document_url,
                collection=collection,
            )
        )
    return assigned


def _is_retryable_item_error(exc: Exception) -> bool:
    return not isinstance(exc, (ValueError, TypeError, FileNotFoundError))


def _acquire_one(
    *,
    candidate: OfficialDocumentCandidate,
    fetcher: BoundedHttpFetcher,
    object_store: Any,
    ordinal: int,
    total: int,
):
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _event(
                "scj.1994_backfill.item_attempt",
                ordinal=ordinal,
                total=total,
                attempt=attempt,
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
            )
            artifact = acquire_candidates(
                candidates=(candidate,),
                fetcher=fetcher,
                object_store=object_store,
            )[0]
            if not object_store.exists(artifact.object_key):
                raise RuntimeError(
                    f"artifact not visible after acquisition: {artifact.object_key}"
                )
            return artifact
        except Exception as exc:
            last_error = exc
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is not None:
                retryable = infrastructure_failure.retryable
            else:
                retryable = _is_retryable_item_error(exc)
            _event(
                "scj.1994_backfill.item_attempt_failed",
                ordinal=ordinal,
                total=total,
                attempt=attempt,
                source_identifier=candidate.source_identifier,
                error_type=type(exc).__name__,
                error=str(exc),
                retryable=retryable,
            )
            if infrastructure_failure is not None and (
                not infrastructure_failure.retryable or attempt == MAX_ATTEMPTS
            ):
                raise GlobalAcquisitionInterruption(
                    infrastructure_failure,
                    exc,
                ) from exc
            if not retryable:
                break
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(8.0, float(2 ** (attempt - 1))))
    assert last_error is not None
    raise last_error


def _restore_recovery_journal(output_dir: Path) -> AcquisitionRecoveryJournal:
    current = output_dir / "recovery-checkpoint.jsonl"
    resume = os.environ.get("SCJ_BACKFILL_RESUME_CHECKPOINT", "").strip()
    if resume:
        resume_path = Path(resume)
        if not resume_path.exists():
            raise FileNotFoundError(f"resume checkpoint does not exist: {resume_path}")
        if resume_path.resolve() != current.resolve():
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(resume_path, current)
    return AcquisitionRecoveryJournal(current)


def _verify_recovered_object(*, object_store: Any, record: RecoveryCheckpointRecord) -> None:
    if record.status != "stored":
        raise ValueError("only stored checkpoint records can be verified")
    assert record.object_key is not None
    response = object_store.client.head_object(
        Bucket=object_store.config.bucket,
        Key=record.object_key,
    )
    content_length = int(response.get("ContentLength") or -1)
    metadata = response.get("Metadata") or {}
    if content_length != record.byte_count:
        raise RuntimeError(
            f"INTEGRITY_MISMATCH byte_count for {record.object_key}: "
            f"expected {record.byte_count}, got {content_length}"
        )
    stored_sha = str(metadata.get("sha256") or "")
    if stored_sha and stored_sha != record.sha256:
        raise RuntimeError(
            f"INTEGRITY_MISMATCH sha256 metadata for {record.object_key}"
        )
    stored_content_type = str(metadata.get("content_type") or "")
    if stored_content_type and stored_content_type != record.content_type:
        raise RuntimeError(
            f"INTEGRITY_MISMATCH content_type metadata for {record.object_key}"
        )


def main() -> None:
    _require_environment()
    if MAX_ATTEMPTS < 1 or MAX_ATTEMPTS > 5:
        raise ValueError("SCJ_BACKFILL_ITEM_ATTEMPTS must be between 1 and 5")

    shard_index = int(os.environ["SCJ_BACKFILL_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_BACKFILL_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid SCJ 1994+ backfill shard coordinates")

    output_dir = Path(os.environ["SCJ_BACKFILL_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    recovery_journal = _restore_recovery_journal(output_dir)
    inventory_path = Path(os.environ["SCJ_1994_INVENTORY_FILE"])
    candidates = _load_assigned(
        path=inventory_path,
        shard_index=shard_index,
        shard_count=shard_count,
    )

    object_store = build_s3_object_store()
    fetcher = BoundedHttpFetcher(
        allowed_hosts=SCJ_DECISION_DOCUMENT_HOSTS,
        max_attempts=4,
        timeout_seconds=120.0,
        max_bytes=512 * 1024 * 1024,
    )
    batch_id = _batch_id()
    ingestion_id = f"{batch_id}-part-{shard_index:03d}"
    manifest = AcquisitionRunManifestBuilder(
        source="scj",
        scope="sentencias-1994-actualidad",
        storage_bucket=object_store.config.bucket,
        ingestion_id=ingestion_id,
        batch_id=batch_id,
        partition_index=shard_index,
        partition_count=shard_count,
    )

    _event(
        "scj.1994_backfill.started",
        batch_id=batch_id,
        ingestion_id=ingestion_id,
        shard_index=shard_index,
        shard_count=shard_count,
        candidate_count=len(candidates),
    )

    completed: list[dict[str, object]] = []
    unavailable: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    interruption: dict[str, object] | None = None
    for ordinal, candidate in enumerate(candidates, start=1):
        recovered = recovery_journal.get(
            source_identifier=candidate.source_identifier,
            document_url=candidate.document_url,
        )
        if recovered is not None and recovered.status == "stored":
            _verify_recovered_object(object_store=object_store, record=recovered)
            assert recovered.sha256 is not None
            assert recovered.object_key is not None
            manifest.record_existing(
                candidate=candidate,
                sha256=recovered.sha256,
                object_key=recovered.object_key,
                byte_count=recovered.byte_count,
                content_type=recovered.content_type or "application/pdf",
                file_extension=recovered.file_extension or "pdf",
            )
            completed.append(
                {
                    "source_identifier": candidate.source_identifier,
                    "document_url": candidate.document_url,
                    "sha256": recovered.sha256,
                    "byte_count": recovered.byte_count,
                    "object_key": recovered.object_key,
                    "already_present": True,
                    "content_type": recovered.content_type,
                    "file_extension": recovered.file_extension,
                    "verification_method": "prior_manifest_and_head",
                    "recovered": True,
                }
            )
            _event(
                "scj.1994_backfill.item_recovered",
                ordinal=ordinal,
                total=len(candidates),
                source_identifier=candidate.source_identifier,
                object_key=recovered.object_key,
            )
            continue
        if recovered is not None and recovered.status == "unavailable":
            manifest.record_unavailable(
                collection=candidate.collection,
                source_identifier=candidate.source_identifier,
                discovery_url=candidate.discovery_url,
                document_url=candidate.document_url,
                error_type=recovered.error_type,
                reason=recovered.reason,
            )
            unavailable.append(
                {
                    "source_identifier": candidate.source_identifier,
                    "document_url": candidate.document_url,
                    "reason": recovered.reason,
                    "error_type": recovered.error_type,
                    "recovered": True,
                }
            )
            continue

        try:
            artifact = _acquire_one(
                candidate=candidate,
                fetcher=fetcher,
                object_store=object_store,
                ordinal=ordinal,
                total=len(candidates),
            )
            manifest.record_artifact(artifact)
            record = {
                "source_identifier": candidate.source_identifier,
                "document_url": candidate.document_url,
                "sha256": artifact.sha256,
                "byte_count": artifact.byte_count,
                "object_key": artifact.object_key,
                "already_present": artifact.already_present,
                "content_type": artifact.content_type,
                "file_extension": artifact.file_extension,
                "verification_method": "downloaded_and_hashed",
            }
            completed.append(record)
            recovery_journal.append(
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
            _event(
                "scj.1994_backfill.item_completed",
                ordinal=ordinal,
                total=len(candidates),
                **record,
            )
        except UnsupportedOfficialDocumentResponse as exc:
            manifest.record_unavailable(
                collection=candidate.collection,
                source_identifier=candidate.source_identifier,
                discovery_url=candidate.discovery_url,
                document_url=candidate.document_url,
                error_type=type(exc).__name__,
                reason=exc.reason,
            )
            unavailable_record = {
                "source_identifier": candidate.source_identifier,
                "document_url": candidate.document_url,
                "reason": exc.reason,
                "error_type": type(exc).__name__,
            }
            unavailable.append(unavailable_record)
            recovery_journal.append(
                RecoveryCheckpointRecord(
                    source_identifier=candidate.source_identifier,
                    document_url=candidate.document_url,
                    status="unavailable",
                    recorded_at=utc_now_z(),
                    error_type=type(exc).__name__,
                    reason=exc.reason,
                )
            )
            _event(
                "scj.1994_backfill.item_unavailable",
                ordinal=ordinal,
                total=len(candidates),
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
                reason=exc.reason,
            )
        except GlobalAcquisitionInterruption as exc:
            interruption = {
                "status": "RUN_INTERRUPTED",
                "cause": exc.failure.kind,
                "retryable": exc.failure.retryable,
                "error_code": exc.failure.code,
                "http_status": exc.failure.http_status,
                "detail": exc.failure.detail,
                "interruption_source_identifier": candidate.source_identifier,
                "interruption_document_url": candidate.document_url,
                "processed_count": len(completed) + len(unavailable) + len(failures),
                "pending_count": len(candidates)
                - (len(completed) + len(unavailable) + len(failures)),
                "resumable": True,
            }
            _write_json(output_dir / "interruption.json", interruption)
            _event("scj.1994_backfill.interrupted", **interruption)
            break
        except Exception as exc:
            manifest.record_failure(
                collection=candidate.collection,
                source_identifier=candidate.source_identifier,
                discovery_url=candidate.discovery_url,
                document_url=candidate.document_url,
                error=exc,
            )
            failure = {
                "source_identifier": candidate.source_identifier,
                "document_url": candidate.document_url,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            failures.append(failure)
            recovery_journal.append(
                RecoveryCheckpointRecord(
                    source_identifier=candidate.source_identifier,
                    document_url=candidate.document_url,
                    status="failed",
                    recorded_at=utc_now_z(),
                    error_type=type(exc).__name__,
                    reason=str(exc)[:2000],
                )
            )
            _event(
                "scj.1994_backfill.item_failed",
                ordinal=ordinal,
                total=len(candidates),
                source_identifier=candidate.source_identifier,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    if interruption is not None:
        summary = {
            **interruption,
            "batch_id": batch_id,
            "ingestion_id": ingestion_id,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "assigned_count": len(candidates),
            "completed_count": len(completed),
            "unavailable_count": len(unavailable),
            "failed_count": len(failures),
        }
        _write_json(output_dir / "summary.json", summary)
        _write_json(output_dir / "failures.json", failures)
        _write_json(output_dir / "unavailable.json", unavailable)
        _write_json(output_dir / "completed.json", completed)
        raise RuntimeError(
            f"SCJ 1994+ shard {shard_index} interrupted: {interruption['cause']}"
        )

    stored_manifest = manifest.commit(object_store=object_store)
    (output_dir / "run-manifest.json").write_bytes(
        stored_manifest.manifest.canonical_bytes()
    )
    summary = {
        "batch_id": batch_id,
        "ingestion_id": ingestion_id,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "assigned_count": len(candidates),
        "completed_count": len(completed),
        "unavailable_count": len(unavailable),
        "failed_count": len(failures),
        "uploaded_count": stored_manifest.manifest.uploaded_count,
        "already_present_count": stored_manifest.manifest.already_present_count,
        "manifest_status": stored_manifest.manifest.status,
        "manifest_object_key": stored_manifest.object_key,
        "manifest_sha256": stored_manifest.payload_sha256,
        "artifact_set_sha256": stored_manifest.manifest.artifact_set_sha256,
        "source_inventory_sha256": stored_manifest.manifest.source_inventory_sha256,
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "failures.json", failures)
    _write_json(output_dir / "unavailable.json", unavailable)
    _write_json(output_dir / "completed.json", completed)
    _event("scj.1994_backfill.completed", **summary)

    if failures:
        raise RuntimeError(
            f"SCJ 1994+ shard {shard_index} completed with {len(failures)} failures"
        )


if __name__ == "__main__":
    main()
