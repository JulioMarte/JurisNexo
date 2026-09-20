from __future__ import annotations

import hashlib
import json
import os
import signal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    acquire_candidates,
    object_key_for,
)
from jurisnexo.acquisition.recovery import (
    AcquisitionRecoveryJournal,
    RecoveryCheckpointRecord,
    S3RecoveryCheckpointMirror,
    classify_infrastructure_error,
    utc_now_z,
)
from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog
from jurisnexo.corpus.artifact_inventory import PostgresRegisteredArtifactInventory

SCJ_PORTAL = "https://consultasentenciascj.poderjudicial.gob.do/"
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


def _inventory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


REQUIRED_ENV = (
    "DATABASE_URL",
    "SCJ_INVENTORY_FILE",
    "SCJ_BACKFILL_SHARD_INDEX",
    "SCJ_BACKFILL_SHARD_COUNT",
    "SCJ_BACKFILL_OUTPUT",
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def _batch_id(*, source: str) -> str:
    explicit = os.environ.get("ACQUISITION_BATCH_ID", "").strip()
    if explicit:
        return explicit
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    if run_id and run_attempt:
        return f"github-{run_id}-{run_attempt}-{source}"
    return f"local-{source}"


def _ingestion_id(*, batch_id: str, shard_index: int) -> str:
    return f"{batch_id}-part-{shard_index:03d}"


def require_environment() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing SCJ backfill configuration: " + ", ".join(missing))


def configure_telemetry(*, shard_index: int, shard_count: int) -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-backfill",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
                "jurisnexo.shard.index": shard_index,
                "jurisnexo.shard.count": shard_count,
            }
        )
    )
    if _env_flag("JURISNEXO_OTEL_CONSOLE", False):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def candidate_from_record(record: dict[str, Any]) -> OfficialDocumentCandidate:
    row = record.get("row")
    if not isinstance(row, dict):
        raise TypeError("SCJ inventory record is missing its row object")
    surface = str(record.get("surface") or "").strip()

    if surface == "decisions":
        document_url = str(row.get("urlBlob") or "").strip()
        expediente_id = str(row.get("idExpediente") or "").strip()
        guid_blob = str(row.get("guidBlob") or "").strip()
        if not expediente_id:
            raise ValueError("SCJ decision lacks idExpediente")
        source_identifier = f"expediente:{expediente_id}"
        if guid_blob:
            source_identifier += f":{guid_blob}"
        collection = "decisions"
    elif surface == "historical":
        document_url = str(row.get("rutaDoc") or "").strip()
        year = str(row.get("ano") or "").strip()
        month = str(row.get("mes") or "").strip()
        parties = " ".join(str(row.get("partes") or "").split())
        if not (year or month or parties):
            raise ValueError("SCJ historical decision lacks a stable source identity")
        source_identifier = f"historical:{year}:{month}:{parties}"
        collection = "historical-decisions"
    elif surface == "bulletins":
        document_url = str(row.get("urlCuerpo") or "").strip()
        body_id = str(row.get("idCuerpo") or "").strip()
        header_id = str(row.get("idCabecera") or "").strip()
        if not body_id:
            raise ValueError("SCJ bulletin lacks idCuerpo")
        source_identifier = f"bulletin:{header_id}:{body_id}"
        collection = "bulletins"
    else:
        raise ValueError(f"unsupported SCJ inventory surface: {surface!r}")

    if not document_url.startswith("https://"):
        raise ValueError(f"SCJ {surface} row lacks an HTTPS document URL")
    host = (urlparse(document_url).hostname or "").casefold()
    if host not in OFFICIAL_SOURCE_HOSTS:
        raise ValueError(f"SCJ inventory references non-allowlisted PDF host: {host}")

    return OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier=source_identifier,
        discovery_url=SCJ_PORTAL,
        document_url=document_url,
        collection=collection,
    )


def assigned_candidates(
    *, inventory_path: Path, shard_index: int, shard_count: int
) -> list[OfficialDocumentCandidate]:
    candidates: list[OfficialDocumentCandidate] = []
    with inventory_path.open(encoding="utf-8") as source:
        assigned_index = 0
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("SCJ inventory JSONL contains a non-object record")
            if assigned_index % shard_count == shard_index:
                candidates.append(candidate_from_record(record))
            assigned_index += 1
    return candidates


def main() -> int:
    _install_signal_handlers()
    require_environment()
    shard_index = int(os.environ["SCJ_BACKFILL_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_BACKFILL_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid backfill shard coordinates")
    output_dir = Path(os.environ["SCJ_BACKFILL_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_telemetry(shard_index=shard_index, shard_count=shard_count)
    tracer = trace.get_tracer("jurisnexo.scj.backfill")
    object_store = build_s3_object_store()
    inventory_path = Path(os.environ["SCJ_INVENTORY_FILE"])
    inventory_sha256 = _inventory_sha256(inventory_path)
    recovery_journal = AcquisitionRecoveryJournal(output_dir / "recovery-checkpoint.jsonl")
    recovery_mirror = S3RecoveryCheckpointMirror(
        object_store=object_store,
        object_key=(
            "_checkpoints/scj/official-corpus/"
            f"{inventory_sha256}/shard-{shard_index:03d}.jsonl"
        ),
        checkpoint_identity=f"scj:official-corpus:{inventory_sha256}:{shard_index}:{shard_count}",
    )
    if not recovery_journal.path.exists() or recovery_journal.path.stat().st_size == 0:
        try:
            recovery_mirror.load_if_present(recovery_journal)
        except Exception as exc:
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is not None:
                interruption = {
                    "status": "RUN_INTERRUPTED",
                    "cause": infrastructure_failure.kind,
                    "phase": "checkpoint_restore",
                    "retryable": infrastructure_failure.retryable,
                    "resumable": True,
                }
                (output_dir / f"backfill-{shard_index:02d}-interruption.json").write_text(
                    json.dumps(interruption, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return 75
            raise
    fetcher = BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)
    candidates = assigned_candidates(
        inventory_path=inventory_path,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    batch_id = _batch_id(source="scj")
    run_manifest = AcquisitionRunManifestBuilder(
        source="scj",
        scope=os.environ.get("ACQUISITION_MANIFEST_SCOPE", "official-corpus").strip(),
        storage_bucket=object_store.config.bucket,
        ingestion_id=_ingestion_id(batch_id=batch_id, shard_index=shard_index),
        batch_id=batch_id,
        partition_index=shard_index,
        partition_count=shard_count,
    )

    acquired = 0
    skipped_verified = 0
    repaired_storage = 0
    bytes_acquired = 0
    failures: list[dict[str, str]] = []
    collection_counts: dict[str, int] = {}
    with tracer.start_as_current_span("scj.backfill.shard") as root:
        root.set_attribute("scj.shard.index", shard_index)
        root.set_attribute("scj.shard.count", shard_count)
        root.set_attribute("scj.shard.candidate_count", len(candidates))
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            catalog = PostgresOfficialArtifactCatalog(
                connection=connection,
                storage_bucket=object_store.config.bucket,
            )
            registered = PostgresRegisteredArtifactInventory(connection=connection).observations_for(
                "supreme_court"
            )
            current = {
                (item.source_identifier, item.document_url): item.sha256 for item in registered
            }
            for index, candidate in enumerate(candidates):
                collection_counts[candidate.collection] = (
                    collection_counts.get(candidate.collection, 0) + 1
                )
                try:
                    with tracer.start_as_current_span("scj.backfill.item") as span:
                        span.set_attribute("scj.shard.item_index", index)
                        span.set_attribute("source_identifier", candidate.source_identifier)
                        span.set_attribute("source.collection", candidate.collection)
                        recovered = recovery_journal.get(
                            source_identifier=candidate.source_identifier,
                            document_url=candidate.document_url,
                        )
                        if recovered is not None and recovered.status == "stored":
                            assert recovered.object_key is not None
                            head = object_store.client.head_object(
                                Bucket=object_store.config.bucket,
                                Key=recovered.object_key,
                            )
                            if int(head.get("ContentLength") or -1) != recovered.byte_count:
                                raise RuntimeError(
                                    f"INTEGRITY_MISMATCH byte_count for {recovered.object_key}"
                                )
                            run_manifest.record_existing(
                                candidate=candidate,
                                sha256=recovered.sha256 or "",
                                object_key=recovered.object_key,
                                byte_count=recovered.byte_count,
                                content_type=recovered.content_type or "application/pdf",
                                file_extension=recovered.file_extension or "pdf",
                            )
                            skipped_verified += 1
                            span.set_attribute("artifact.recovered", True)
                            continue

                        existing_digest = current.get(
                            (candidate.source_identifier, candidate.document_url)
                        )
                        if existing_digest is not None:
                            key = object_key_for(
                                source="supreme_court",
                                collection=candidate.collection,
                                sha256=existing_digest,
                            )
                            if object_store.exists(key):
                                head = object_store.client.head_object(
                                    Bucket=object_store.config.bucket,
                                    Key=key,
                                )
                                byte_count = int(head.get("ContentLength") or 0)
                                file_extension = key.rsplit(".", 1)[-1]
                                content_type = str(
                                    (head.get("Metadata") or {}).get("content_type")
                                    or "application/pdf"
                                )
                                run_manifest.record_existing(
                                    candidate=candidate,
                                    sha256=existing_digest,
                                    object_key=key,
                                    byte_count=byte_count,
                                    content_type=content_type,
                                    file_extension=file_extension,
                                )
                                recovery_journal.append(
                                    RecoveryCheckpointRecord(
                                        source_identifier=candidate.source_identifier,
                                        document_url=candidate.document_url,
                                        status="stored",
                                        recorded_at=utc_now_z(),
                                        sha256=existing_digest,
                                        object_key=key,
                                        byte_count=byte_count,
                                        content_type=content_type,
                                        file_extension=file_extension,
                                    )
                                )
                                recovery_mirror.persist(recovery_journal)
                                skipped_verified += 1
                                span.set_attribute("artifact.already_verified", True)
                                continue
                            repaired_storage += 1
                            span.set_attribute("artifact.storage_repair", True)

                        artifacts = acquire_candidates(
                            candidates=(candidate,),
                            fetcher=fetcher,
                            object_store=object_store,
                            artifact_catalog=catalog,
                        )
                        if len(artifacts) != 1:
                            raise RuntimeError(
                                "SCJ backfill item did not produce exactly one artifact"
                            )
                        artifact = artifacts[0]
                        run_manifest.record_artifact(artifact)
                        current[(candidate.source_identifier, candidate.document_url)] = (
                            artifact.sha256
                        )
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
                        acquired += 1
                        bytes_acquired += artifact.byte_count
                        span.set_attribute("artifact.sha256_prefix", artifact.sha256[:12])
                except Exception as exc:
                    infrastructure_failure = classify_infrastructure_error(exc)
                    if infrastructure_failure is not None:
                        interruption = {
                            "status": "RUN_INTERRUPTED",
                            "cause": infrastructure_failure.kind,
                            "retryable": infrastructure_failure.retryable,
                            "error_code": infrastructure_failure.code,
                            "http_status": infrastructure_failure.http_status,
                            "detail": infrastructure_failure.detail,
                            "processed_count": acquired + skipped_verified + len(failures),
                            "pending_count": max(
                                0,
                                len(candidates) - acquired - skipped_verified - len(failures),
                            ),
                            "resumable": True,
                        }
                        (output_dir / f"backfill-{shard_index:02d}-interruption.json").write_text(
                            json.dumps(interruption, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        print(json.dumps({"event": "scj_backfill_interrupted", **interruption}), flush=True)
                        return 75
                    run_manifest.record_failure(
                        collection=candidate.collection,
                        source_identifier=candidate.source_identifier,
                        discovery_url=candidate.discovery_url,
                        document_url=candidate.document_url,
                        error=exc,
                    )
                    failure = {
                        "source_identifier": candidate.source_identifier,
                        "collection": candidate.collection,
                        "document_url": candidate.document_url,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2000],
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
                    except Exception as checkpoint_exc:
                        checkpoint_failure = classify_infrastructure_error(checkpoint_exc)
                        if checkpoint_failure is not None:
                            interruption = {
                                "status": "RUN_INTERRUPTED",
                                "cause": checkpoint_failure.kind,
                                "phase": "checkpoint_persist",
                                "retryable": checkpoint_failure.retryable,
                                "resumable": True,
                            }
                            (output_dir / f"backfill-{shard_index:02d}-interruption.json").write_text(
                                json.dumps(interruption, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8",
                            )
                            return 75
                        raise
                    print(
                        json.dumps(
                            {"event": "scj_backfill_item_failed", **failure},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )

                if (index + 1) % 100 == 0 or index + 1 == len(candidates):
                    print(
                        json.dumps(
                            {
                                "event": "scj_backfill_progress",
                                "shard_index": shard_index,
                                "processed": index + 1,
                                "total": len(candidates),
                                "acquired": acquired,
                                "skipped_verified": skipped_verified,
                                "storage_repairs": repaired_storage,
                                "failures": len(failures),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

        try:
            stored_manifest = run_manifest.commit(object_store=object_store)
        except Exception as exc:
            infrastructure_failure = classify_infrastructure_error(exc)
            if infrastructure_failure is None:
                raise
            interruption = {
                "status": "RUN_INTERRUPTED",
                "cause": infrastructure_failure.kind,
                "phase": "manifest_commit",
                "retryable": infrastructure_failure.retryable,
                "resumable": True,
            }
            (output_dir / f"backfill-{shard_index:02d}-interruption.json").write_text(
                json.dumps(interruption, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return 75
        (output_dir / f"backfill-{shard_index:02d}-run-manifest.json").write_bytes(
            stored_manifest.manifest.canonical_bytes()
        )
        summary = {
            "status": "PASS" if not failures else "INCOMPLETE",
            "shard_index": shard_index,
            "shard_count": shard_count,
            "candidate_count": len(candidates),
            "collection_counts": dict(sorted(collection_counts.items())),
            "acquired_or_repaired_count": acquired,
            "skipped_verified_count": skipped_verified,
            "storage_repair_count": repaired_storage,
            "failure_count": len(failures),
            "bytes_acquired": bytes_acquired,
            "run_manifest_object_key": stored_manifest.object_key,
            "run_manifest_sha256": stored_manifest.payload_sha256,
        }
        (output_dir / f"backfill-{shard_index:02d}-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        with (output_dir / f"backfill-{shard_index:02d}-failures.jsonl").open(
            "w", encoding="utf-8"
        ) as handle:
            for failure in failures:
                handle.write(json.dumps(failure, ensure_ascii=False, sort_keys=True) + "\n")
        root.set_attribute("scj.shard.acquired_count", acquired)
        root.set_attribute("scj.shard.skipped_verified_count", skipped_verified)
        root.set_attribute("scj.shard.failure_count", len(failures))
        root.set_attribute("scj.shard.bytes_acquired", bytes_acquired)
        root.set_attribute("acquisition.run_manifest_key", stored_manifest.object_key)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
