from __future__ import annotations

import json
import os
import shutil
import signal
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
    S3RecoveryCheckpointMirror,
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
_STOP_SIGNAL: str | None = None


def _capture_stop_signal(signum: int, _frame: object) -> None:
    global _STOP_SIGNAL
    try:
        _STOP_SIGNAL = signal.Signals(signum).name
    except ValueError:
        _STOP_SIGNAL = str(signum)


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGTERM, _capture_stop_signal)
    signal.signal(signal.SIGINT, _capture_stop_signal)


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


def _interruption_from_failure(
    *,
    failure: object,
    candidate: OfficialDocumentCandidate | None,
    processed_count: int,
    total_count: int,
    phase: str,
) -> dict[str, object]:
    kind = getattr(failure, "kind", "unknown_infrastructure_error")
    retryable = bool(getattr(failure, "retryable", False))
    code = str(getattr(failure, "code", ""))
    http_status = int(getattr(failure, "http_status", 0))
    detail = str(getattr(failure, "detail", ""))
    return {
        "status": "RUN_INTERRUPTED",
        "cause": kind,
        "phase": phase,
        "retryable": retryable,
        "error_code": code,
        "http_status": http_status,
        "detail": detail,
        "interruption_source_identifier": (
            candidate.source_identifier if candidate is not None else None
        ),
        "interruption_document_url": (
            candidate.document_url if candidate is not None else None
        ),
        "processed_count": processed_count,
        "pending_count": max(0, total_count - processed_count),
        "resumable": True,
    }


def _signal_interruption(
    *,
    candidate: OfficialDocumentCandidate | None,
    processed_count: int,
    total_count: int,
) -> dict[str, object]:
    return {
        "status": "RUN_INTERRUPTED",
        "cause": "runner_signal",
        "phase": "acquisition",
        "retryable": True,
        "error_code": "",
        "http_status": 0,
        "detail": f"received {_STOP_SIGNAL or 'termination signal'}",
        "interruption_source_identifier": (
            candidate.source_identifier if candidate is not None else None
        ),
        "interruption_document_url": (
            candidate.document_url if candidate is not None else None
        ),
        "processed_count": processed_count,
        "pending_count": max(0, total_count - processed_count),
        "resumable": True,
    }


def _persist_partial_evidence(
    *,
    output_dir: Path,
    summary: dict[str, object],
    completed: list[dict[str, object]],
    unavailable: list[dict[str, object]],
    failures: list[dict[str, object]],
) -> None:
    _write_json(output_dir / "interruption.json", summary)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "failures.json", failures)
    _write_json(output_dir / "unavailable.json", unavailable)
    _write_json(output_dir / "completed.json", completed)


def main() -> int:
    _install_signal_handlers()
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
    recovery_mirror = S3RecoveryCheckpointMirror(
        object_store=object_store,
        object_key=(
            "_checkpoints/scj/sentencias-1994-actualidad/"
            f"shard-{shard_index:03d}.jsonl"
        ),
    )
    if not recovery_journal.path.exists() or recovery_journal.path.stat().st_size == 0:
        try:
            recovery_mirror.load_if_present(recovery_journal)
        except Exception as exc:
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is not None:
                summary = _interruption_from_failure(
                    failure=infrastructure_failure,
                    candidate=None,
                    processed_count=0,
                    total_count=len(candidates),
                    phase="checkpoint_restore",
                )
                _persist_partial_evidence(
                    output_dir=output_dir,
                    summary=summary,
                    completed=[],
                    unavailable=[],
                    failures=[],
                )
                _event("scj.1994_backfill.interrupted", **summary)
                return 75
            raise
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
        certified_inventory_sha256=(
            os.environ.get("SCJ_CERTIFIED_INVENTORY_SHA256", "").strip() or None
        ),
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
        if _STOP_SIGNAL is not None:
            processed_count = len(completed) + len(unavailable) + len(failures)
            interruption = _signal_interruption(
                candidate=candidate,
                processed_count=processed_count,
                total_count=len(candidates),
            )
            _persist_partial_evidence(
                output_dir=output_dir,
                summary=interruption,
                completed=completed,
                unavailable=unavailable,
                failures=failures,
            )
            _event("scj.1994_backfill.interrupted", **interruption)
            break

        recovered = recovery_journal.get(
            source_identifier=candidate.source_identifier,
            document_url=candidate.document_url,
        )
        if recovered is not None and recovered.status == "stored":
            try:
                _verify_recovered_object(object_store=object_store, record=recovered)
            except Exception as exc:
                infrastructure_failure = classify_infrastructure_error(exc)
                if infrastructure_failure is None:
                    raise
                processed_count = len(completed) + len(unavailable) + len(failures)
                interruption = _interruption_from_failure(
                    failure=infrastructure_failure,
                    candidate=candidate,
                    processed_count=processed_count,
                    total_count=len(candidates),
                    phase="resume_verification",
                )
                _persist_partial_evidence(
                    output_dir=output_dir,
                    summary=interruption,
                    completed=completed,
                    unavailable=unavailable,
                    failures=failures,
                )
                _event("scj.1994_backfill.interrupted", **interruption)
                break
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
            try:
                recovery_mirror.persist(recovery_journal)
            except Exception as exc:
                infrastructure_failure = classify_infrastructure_error(exc)
                if infrastructure_failure is None:
                    raise
                interruption = _interruption_from_failure(
                    failure=infrastructure_failure,
                    candidate=candidate,
                    processed_count=len(completed) + len(unavailable) + len(failures),
                    total_count=len(candidates),
                    phase="checkpoint_persist",
                )
                _persist_partial_evidence(
                    output_dir=output_dir,
                    summary=interruption,
                    completed=completed,
                    unavailable=unavailable,
                    failures=failures,
                )
                _event("scj.1994_backfill.interrupted", **interruption)
                break
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
            try:
                recovery_mirror.persist(recovery_journal)
            except Exception as mirror_exc:
                infrastructure_failure = classify_infrastructure_error(mirror_exc)
                if infrastructure_failure is None:
                    raise
                interruption = _interruption_from_failure(
                    failure=infrastructure_failure,
                    candidate=candidate,
                    processed_count=len(completed) + len(unavailable) + len(failures),
                    total_count=len(candidates),
                    phase="checkpoint_persist",
                )
                _persist_partial_evidence(
                    output_dir=output_dir,
                    summary=interruption,
                    completed=completed,
                    unavailable=unavailable,
                    failures=failures,
                )
                _event("scj.1994_backfill.interrupted", **interruption)
                break
            _event(
                "scj.1994_backfill.item_unavailable",
                ordinal=ordinal,
                total=len(candidates),
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
                reason=exc.reason,
            )
        except GlobalAcquisitionInterruption as exc:
            processed_count = len(completed) + len(unavailable) + len(failures)
            interruption = _interruption_from_failure(
                failure=exc.failure,
                candidate=candidate,
                processed_count=processed_count,
                total_count=len(candidates),
                phase="acquisition",
            )
            _persist_partial_evidence(
                output_dir=output_dir,
                summary=interruption,
                completed=completed,
                unavailable=unavailable,
                failures=failures,
            )
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
            try:
                recovery_mirror.persist(recovery_journal)
            except Exception as mirror_exc:
                infrastructure_failure = classify_infrastructure_error(mirror_exc)
                if infrastructure_failure is None:
                    raise
                interruption = _interruption_from_failure(
                    failure=infrastructure_failure,
                    candidate=candidate,
                    processed_count=len(completed) + len(unavailable) + len(failures),
                    total_count=len(candidates),
                    phase="checkpoint_persist",
                )
                _persist_partial_evidence(
                    output_dir=output_dir,
                    summary=interruption,
                    completed=completed,
                    unavailable=unavailable,
                    failures=failures,
                )
                _event("scj.1994_backfill.interrupted", **interruption)
                break
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
        _persist_partial_evidence(
            output_dir=output_dir,
            summary=summary,
            completed=completed,
            unavailable=unavailable,
            failures=failures,
        )
        return 75

    try:
        stored_manifest = manifest.commit(object_store=object_store)
    except Exception as exc:
        infrastructure_failure = classify_infrastructure_error(exc)
        if infrastructure_failure is None:
            raise
        processed_count = len(completed) + len(unavailable) + len(failures)
        interruption = _interruption_from_failure(
            failure=infrastructure_failure,
            candidate=None,
            processed_count=processed_count,
            total_count=len(candidates),
            phase="manifest_commit",
        )
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
        _persist_partial_evidence(
            output_dir=output_dir,
            summary=summary,
            completed=completed,
            unavailable=unavailable,
            failures=failures,
        )
        _event("scj.1994_backfill.interrupted", **summary)
        return 75
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
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
