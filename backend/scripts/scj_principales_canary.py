from __future__ import annotations

import hashlib
import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from jurisnexo.acquisition.http_fetcher import OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.manifest import AcquisitionRunManifestBuilder
from jurisnexo.acquisition.playwright_fetcher import PlaywrightVerifiedFetcher
from jurisnexo.acquisition.official_corpus import (
    SCJ_PRINCIPALES_URL,
    acquire_candidates,
    discover_scj_principales_candidates_from_html,
)
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store

OUT = Path(os.environ.get("SCJ_PRINCIPALES_CANARY_OUTPUT", "scj-principales-canary-output"))
LIMIT = int(os.environ.get("SCJ_PRINCIPALES_CANARY_LIMIT", "1"))


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


def _ingestion_id() -> str | None:
    explicit = os.environ.get("ACQUISITION_INGESTION_ID", "").strip()
    if explicit:
        return explicit
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    if run_id and run_attempt:
        return f"github-{run_id}-{run_attempt}-scj-principales-canary"
    return None


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_canary(*, fetcher: PlaywrightVerifiedFetcher, object_store: S3ObjectStore) -> None:
    _event("principales.discovery.fetch_started", url=SCJ_PRINCIPALES_URL)
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
    _event(
        "principales.discovery.fetch_completed",
        byte_count=len(html_bytes),
        sha256=html_sha256,
    )

    html = html_bytes.decode("utf-8", errors="replace")
    discovered = discover_scj_principales_candidates_from_html(
        html=html,
        page_url=SCJ_PRINCIPALES_URL,
    )
    if not discovered:
        raise RuntimeError(
            "official Principales page exposed no recognized official PDF links; "
            "inspect principales-page.html for source drift"
        )

    selected = discovered[:LIMIT]
    inventory = [
        {
            "source": candidate.source,
            "source_identifier": candidate.source_identifier,
            "collection": candidate.collection,
            "discovery_url": candidate.discovery_url,
            "document_url": candidate.document_url,
        }
        for candidate in discovered
    ]
    _write_json(OUT / "principales-discovered.json", inventory)
    _event(
        "principales.discovery.completed",
        discovered_count=len(discovered),
        selected_count=len(selected),
        selected_source_identifiers=[candidate.source_identifier for candidate in selected],
    )

    ingestion_id = _ingestion_id()
    run_manifest = AcquisitionRunManifestBuilder(
        source="scj",
        scope="principales-sentencias",
        storage_bucket=object_store.config.bucket,
        ingestion_id=ingestion_id,
        batch_id=ingestion_id,
    )

    artifacts = acquire_candidates(
        candidates=selected,
        fetcher=fetcher,
        object_store=object_store,
    )
    if len(artifacts) != len(selected):
        raise RuntimeError(
            "Principales canary acquisition did not return one artifact per selected candidate"
        )

    artifact_summaries: list[dict[str, object]] = []
    for artifact in artifacts:
        if not object_store.exists(artifact.object_key):
            raise RuntimeError(
                f"stored Principales artifact is not visible after upload: {artifact.object_key}"
            )
        run_manifest.record_artifact(artifact)
        locator = object_store.config.locator_for(artifact.object_key)
        artifact_summaries.append(
            {
                "source_identifier": artifact.candidate.source_identifier,
                "document_url": artifact.candidate.document_url,
                "sha256": artifact.sha256,
                "byte_count": artifact.byte_count,
                "object_key": artifact.object_key,
                "storage_bucket": object_store.config.bucket,
                "storage_locator": locator,
                "already_present": artifact.already_present,
                "verification_method": "downloaded_and_hashed",
            }
        )
        _event(
            "principales.artifact.verified",
            source_identifier=artifact.candidate.source_identifier,
            sha256=artifact.sha256,
            byte_count=artifact.byte_count,
            object_key=artifact.object_key,
            storage_bucket=object_store.config.bucket,
            already_present=artifact.already_present,
            verification_method="downloaded_and_hashed",
        )

    stored_manifest = run_manifest.commit(object_store=object_store)
    (OUT / "run-manifest.json").write_bytes(stored_manifest.manifest.canonical_bytes())
    if not object_store.exists(stored_manifest.object_key):
        raise RuntimeError(f"run manifest is not visible after upload: {stored_manifest.object_key}")

    summary = {
        "status": "PASS",
        "page_url": SCJ_PRINCIPALES_URL,
        "page_sha256": html_sha256,
        "discovered_count": len(discovered),
        "selected_count": len(selected),
        "new_upload_count": sum(not item.already_present for item in artifacts),
        "already_present_count": sum(item.already_present for item in artifacts),
        "artifacts": artifact_summaries,
        "run_manifest_object_key": stored_manifest.object_key,
        "run_manifest_sha256": stored_manifest.payload_sha256,
        "run_manifest_locator": object_store.config.locator_for(stored_manifest.object_key),
    }
    _write_json(OUT / "summary.json", summary)
    _event(
        "principales.canary.completed",
        status="PASS",
        discovered_count=len(discovered),
        selected_count=len(selected),
        new_upload_count=summary["new_upload_count"],
        already_present_count=summary["already_present_count"],
        run_manifest_object_key=stored_manifest.object_key,
        run_manifest_sha256=stored_manifest.payload_sha256,
    )


def main() -> None:
    if LIMIT < 1 or LIMIT > 10:
        raise ValueError("SCJ_PRINCIPALES_CANARY_LIMIT must be between 1 and 10")

    OUT.mkdir(parents=True, exist_ok=True)
    _event("principales.canary.started", page_url=SCJ_PRINCIPALES_URL, limit=LIMIT)

    try:
        object_store = build_s3_object_store()
        with PlaywrightVerifiedFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS) as fetcher:
            _run_canary(fetcher=fetcher, object_store=object_store)
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "page_url": SCJ_PRINCIPALES_URL,
        }
        _write_json(OUT / "failure.json", failure)
        _event(
            "principales.canary.failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
