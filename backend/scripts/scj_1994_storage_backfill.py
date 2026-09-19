from __future__ import annotations

import json
import os
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.official_corpus import OfficialDocumentCandidate, acquire_candidates
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
            _event(
                "scj.1994_backfill.item_attempt_failed",
                ordinal=ordinal,
                total=total,
                attempt=attempt,
                source_identifier=candidate.source_identifier,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(8.0, float(2 ** (attempt - 1))))
    assert last_error is not None
    raise last_error


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
    inventory_path = Path(os.environ["SCJ_1994_INVENTORY_FILE"])
    candidates = _load_assigned(
        path=inventory_path,
        shard_index=shard_index,
        shard_count=shard_count,
    )

    object_store = build_s3_object_store()
    fetcher = BoundedHttpFetcher(
        allowed_hosts=OFFICIAL_SOURCE_HOSTS,
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
    failures: list[dict[str, object]] = []
    for ordinal, candidate in enumerate(candidates, start=1):
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
                "verification_method": "downloaded_and_hashed",
            }
            completed.append(record)
            _event(
                "scj.1994_backfill.item_completed",
                ordinal=ordinal,
                total=len(candidates),
                **record,
            )
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
            _event(
                "scj.1994_backfill.item_failed",
                ordinal=ordinal,
                total=len(candidates),
                source_identifier=candidate.source_identifier,
                error_type=type(exc).__name__,
                error=str(exc),
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
    _write_json(output_dir / "completed.json", completed)
    _event("scj.1994_backfill.completed", **summary)

    if failures:
        raise RuntimeError(
            f"SCJ 1994+ shard {shard_index} completed with {len(failures)} failures"
        )


if __name__ == "__main__":
    main()
