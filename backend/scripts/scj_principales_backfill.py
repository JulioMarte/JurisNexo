from __future__ import annotations

import hashlib
import json
import os
import signal
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from jurisnexo.acquisition.http_fetcher import OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.official_corpus import (
    SCJ_PRINCIPALES_URL,
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
    acquire_candidates,
    discover_scj_principales_candidates_from_html,
)
from jurisnexo.acquisition.playwright_fetcher import PlaywrightVerifiedFetcher
from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    GlobalAcquisitionInterruption,
    RecoveryCheckpointRecord,
    S3RecoveryCheckpointMirror,
    classify_infrastructure_error,
    utc_now_z,
)
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store

OUT = Path(os.environ.get("SCJ_PRINCIPALES_BACKFILL_OUTPUT", "scj-principales-backfill-output"))
EXPECTED_COUNT = int(os.environ.get("SCJ_PRINCIPALES_EXPECTED_COUNT", "36"))
MAX_ATTEMPTS = int(os.environ.get("SCJ_PRINCIPALES_ITEM_ATTEMPTS", "3"))
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


def _ingestion_id() -> str:
    explicit = os.environ.get("ACQUISITION_INGESTION_ID", "").strip()
    if explicit:
        return explicit
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    if run_id and run_attempt:
        return f"github-{run_id}-{run_attempt}-scj-principales-full"
    return f"local-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-scj-principales-full"


def _discover(fetcher: PlaywrightVerifiedFetcher) -> tuple[OfficialDocumentCandidate, ...]:
    _event("principales.backfill.discovery_started", url=SCJ_PRINCIPALES_URL)
    html_bytes = fetcher.get_bytes(SCJ_PRINCIPALES_URL)
    html_sha256 = hashlib.sha256(html_bytes).hexdigest()
    (OUT / "principales-page.html").write_bytes(html_bytes)
    _write_json(
        OUT / "principales-page-observation.json",
        {
            "url": SCJ_PRINCIPALES_URL,
            "byte_count": len(html_bytes),
            "sha256": html_sha256,
        },
    )
    candidates = discover_scj_principales_candidates_from_html(
        html=html_bytes.decode("utf-8", errors="replace"),
        page_url=SCJ_PRINCIPALES_URL,
    )
    _write_json(
        OUT / "principales-discovered.json",
        [
            {
                "source": candidate.source,
                "source_identifier": candidate.source_identifier,
                "collection": candidate.collection,
                "discovery_url": candidate.discovery_url,
                "document_url": candidate.document_url,
            }
            for candidate in candidates
        ],
    )
    _event(
        "principales.backfill.discovery_completed",
        discovered_count=len(candidates),
        expected_count=EXPECTED_COUNT,
        page_sha256=html_sha256,
    )
    if len(candidates) != EXPECTED_COUNT:
        raise RuntimeError(
            f"Principales discovery drift: expected {EXPECTED_COUNT}, found {len(candidates)}"
        )
    return candidates


def _acquire_one(
    *,
    fetcher: PlaywrightVerifiedFetcher,
    store: S3ObjectStore,
    candidate: OfficialDocumentCandidate,
    index: int,
    total: int,
) -> StoredOfficialArtifact:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _event(
                "principales.backfill.item_attempt",
                index=index,
                total=total,
                attempt=attempt,
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
            )
            artifact = acquire_candidates(
                candidates=(candidate,),
                fetcher=fetcher,
                object_store=store,
            )[0]
            if not store.exists(artifact.object_key):
                raise RuntimeError(
                    f"artifact not visible after acquisition: {artifact.object_key}"
                )
            return artifact
        except Exception as exc:
            last_error = exc
            infrastructure_failure = classify_infrastructure_error(exc)
            _event(
                "principales.backfill.item_attempt_failed",
                index=index,
                total=total,
                attempt=attempt,
                source_identifier=candidate.source_identifier,
                error_type=type(exc).__name__,
                error=str(exc),
                infrastructure_failure=(
                    infrastructure_failure.kind if infrastructure_failure else None
                ),
            )
            if infrastructure_failure is not None and (
                not infrastructure_failure.retryable or attempt == MAX_ATTEMPTS
            ):
                raise GlobalAcquisitionInterruption(
                    infrastructure_failure,
                    exc,
                ) from exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(float(attempt))
    assert last_error is not None
    raise last_error


def main() -> int:
    _install_signal_handlers()
    if EXPECTED_COUNT < 1:
        raise ValueError("SCJ_PRINCIPALES_EXPECTED_COUNT must be positive")
    if MAX_ATTEMPTS < 1:
        raise ValueError("SCJ_PRINCIPALES_ITEM_ATTEMPTS must be positive")

    OUT.mkdir(parents=True, exist_ok=True)
    ingestion_id = _ingestion_id()
    _event(
        "principales.backfill.started",
        ingestion_id=ingestion_id,
        expected_count=EXPECTED_COUNT,
        max_attempts=MAX_ATTEMPTS,
    )

    store = build_s3_object_store()
    recovery_journal = AcquisitionRecoveryJournal(OUT / "recovery-checkpoint.jsonl")
    recovery_mirror = S3RecoveryCheckpointMirror(
        object_store=store,
        object_key=f"_checkpoints/scj/principales-sentencias/{ingestion_id}/full.jsonl",
        checkpoint_identity=f"scj:principales-sentencias:{ingestion_id}",
    )
    if not recovery_journal.path.exists() or recovery_journal.path.stat().st_size == 0:
        try:
            recovery_mirror.load_if_present(recovery_journal)
        except Exception as exc:
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is not None:
                _write_json(
                    OUT / "interruption.json",
                    {
                        "status": "RUN_INTERRUPTED",
                        "cause": infrastructure_failure.kind,
                        "phase": "checkpoint_restore",
                        "retryable": infrastructure_failure.retryable,
                        "resumable": True,
                    },
                )
                return 75
            raise
    manifest = AcquisitionRunManifestBuilder(
        source="scj",
        scope="principales-sentencias",
        storage_bucket=store.config.bucket,
        ingestion_id=ingestion_id,
        batch_id=ingestion_id,
    )
    failures: list[dict[str, object]] = []
    artifacts: list[dict[str, object]] = []

    try:
        with PlaywrightVerifiedFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS) as fetcher:
            candidates = _discover(fetcher)
            total = len(candidates)
            for index, candidate in enumerate(candidates, start=1):
                if _STOP_SIGNAL is not None:
                    _write_json(
                        OUT / "interruption.json",
                        {
                            "status": "RUN_INTERRUPTED",
                            "cause": "runner_signal",
                            "phase": "acquisition",
                            "retryable": True,
                            "signal": _STOP_SIGNAL,
                            "resumable": True,
                        },
                    )
                    return 75
                try:
                    recovered = recovery_journal.get(
                        source_identifier=candidate.source_identifier,
                        document_url=candidate.document_url,
                    )
                    if recovered is not None and recovered.status == "stored":
                        assert recovered.object_key is not None
                        head = store.client.head_object(
                            Bucket=store.config.bucket,
                            Key=recovered.object_key,
                        )
                        if int(head.get("ContentLength") or -1) != recovered.byte_count:
                            raise RuntimeError(
                                f"INTEGRITY_MISMATCH byte_count for {recovered.object_key}"
                            )
                        manifest.record_existing(
                            candidate=candidate,
                            sha256=recovered.sha256 or "",
                            object_key=recovered.object_key,
                            byte_count=recovered.byte_count,
                            content_type=recovered.content_type or "application/pdf",
                            file_extension=recovered.file_extension or "pdf",
                        )
                        artifacts.append(
                            {
                                "index": index,
                                "source_identifier": candidate.source_identifier,
                                "document_url": candidate.document_url,
                                "sha256": recovered.sha256,
                                "byte_count": recovered.byte_count,
                                "object_key": recovered.object_key,
                                "already_present": True,
                                "verification_method": "prior_manifest_and_head",
                                "recovered": True,
                            }
                        )
                        continue
                    artifact = _acquire_one(
                        fetcher=fetcher,
                        store=store,
                        candidate=candidate,
                        index=index,
                        total=total,
                    )
                    manifest.record_artifact(artifact)
                    record = {
                        "index": index,
                        "source_identifier": candidate.source_identifier,
                        "document_url": candidate.document_url,
                        "sha256": artifact.sha256,
                        "byte_count": artifact.byte_count,
                        "object_key": artifact.object_key,
                        "already_present": artifact.already_present,
                        "verification_method": "downloaded_and_hashed",
                    }
                    artifacts.append(record)
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
                    recovery_mirror.persist(recovery_journal)
                    _event("principales.backfill.item_completed", **record)
                except GlobalAcquisitionInterruption as exc:
                    interruption = {
                        "status": "RUN_INTERRUPTED",
                        "cause": exc.failure.kind,
                        "retryable": exc.failure.retryable,
                        "error_code": exc.failure.code,
                        "http_status": exc.failure.http_status,
                        "detail": exc.failure.detail,
                        "processed_count": len(artifacts) + len(failures),
                        "pending_count": total - len(artifacts) - len(failures),
                        "resumable": True,
                    }
                    _write_json(OUT / "interruption.json", interruption)
                    _write_json(OUT / "summary.json", interruption)
                    _event("principales.backfill.interrupted", **interruption)
                    return 75
                except Exception as exc:
                    manifest.record_failure(
                        collection=candidate.collection,
                        source_identifier=candidate.source_identifier,
                        discovery_url=candidate.discovery_url,
                        document_url=candidate.document_url,
                        error=exc,
                    )
                    failure = {
                        "index": index,
                        "source_identifier": candidate.source_identifier,
                        "document_url": candidate.document_url,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    failures.append(failure)
                    _event(
                        "principales.backfill.item_failed",
                        index=index,
                        total=total,
                        source_identifier=candidate.source_identifier,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )

        try:
            stored_manifest = manifest.commit(object_store=store)
        except Exception as exc:
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is None:
                raise
            _write_json(
                OUT / "interruption.json",
                {
                    "status": "RUN_INTERRUPTED",
                    "cause": infrastructure_failure.kind,
                    "phase": "manifest_commit",
                    "retryable": infrastructure_failure.retryable,
                    "resumable": True,
                },
            )
            return 75
        (OUT / "run-manifest.json").write_bytes(
            stored_manifest.manifest.canonical_bytes()
        )
        if not store.exists(stored_manifest.object_key):
            raise RuntimeError(
                f"run manifest not visible after commit: {stored_manifest.object_key}"
            )

        summary = {
            "status": "PASS" if not failures else "INCOMPLETE",
            "ingestion_id": ingestion_id,
            "expected_count": EXPECTED_COUNT,
            "discovered_count": stored_manifest.manifest.discovered_count,
            "uploaded_count": stored_manifest.manifest.uploaded_count,
            "already_present_count": stored_manifest.manifest.already_present_count,
            "failed_count": stored_manifest.manifest.failed_count,
            "artifact_count": len(artifacts),
            "run_manifest_object_key": stored_manifest.object_key,
            "run_manifest_sha256": stored_manifest.payload_sha256,
            "artifact_set_sha256": stored_manifest.manifest.artifact_set_sha256,
            "source_inventory_sha256": stored_manifest.manifest.source_inventory_sha256,
            "artifacts": artifacts,
        }
        _write_json(OUT / "summary.json", summary)
        _write_json(OUT / "failures.json", failures)
        _event(
            "principales.backfill.completed",
            status=summary["status"],
            uploaded_count=summary["uploaded_count"],
            already_present_count=summary["already_present_count"],
            failed_count=summary["failed_count"],
            run_manifest_object_key=stored_manifest.object_key,
        )
        if failures:
            return 1
        if len(artifacts) != EXPECTED_COUNT:
            _write_json(
                OUT / "failure.json",
                {
                    "status": "INCOMPLETE",
                    "reason": "artifact_count_mismatch",
                    "artifact_count": len(artifacts),
                    "expected_count": EXPECTED_COUNT,
                },
            )
            return 1
        return 0
    except Exception as exc:
        infrastructure_failure = classify_infrastructure_error(exc)
        if infrastructure_failure is not None:
            _write_json(
                OUT / "interruption.json",
                {
                    "status": "RUN_INTERRUPTED",
                    "cause": infrastructure_failure.kind,
                    "phase": "runtime",
                    "retryable": infrastructure_failure.retryable,
                    "resumable": True,
                    "recorded_failure_count": len(failures),
                    "completed_artifact_count": len(artifacts),
                },
            )
            return 75
        _write_json(
            OUT / "failure.json",
            {
                "status": "FAIL",
                "ingestion_id": ingestion_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "recorded_failure_count": len(failures),
                "completed_artifact_count": len(artifacts),
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
