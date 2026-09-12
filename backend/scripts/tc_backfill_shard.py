from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    acquire_candidates,
    discover_pdf_link,
    object_key_for,
)
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, S3ObjectStoreConfig
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog
from jurisnexo.corpus.artifact_inventory import PostgresRegisteredArtifactInventory

REQUIRED_ENV = (
    "DATABASE_URL",
    "JURISNEXO_S3_BUCKET",
    "JURISNEXO_S3_ENDPOINT_URL",
    "JURISNEXO_S3_REGION",
    "JURISNEXO_S3_ACCESS_KEY_ID",
    "JURISNEXO_S3_SECRET_ACCESS_KEY",
    "TC_INVENTORY_FILE",
    "TC_BACKFILL_SHARD_INDEX",
    "TC_BACKFILL_SHARD_COUNT",
    "TC_BACKFILL_OUTPUT",
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def require_environment() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing TC backfill configuration: " + ", ".join(missing))


def configure_telemetry(*, shard_index: int, shard_count: int) -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-tc-backfill",
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


def is_s3_not_found(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
    return status == 404 or code in {"404", "NoSuchKey", "NotFound"}


def build_object_store() -> S3ObjectStore:
    force_path_style = _env_flag("JURISNEXO_S3_FORCE_PATH_STYLE", True)
    config = S3ObjectStoreConfig(
        bucket=os.environ["JURISNEXO_S3_BUCKET"],
        endpoint_url=os.environ["JURISNEXO_S3_ENDPOINT_URL"],
        region=os.environ["JURISNEXO_S3_REGION"],
        force_path_style=force_path_style,
    )
    client: Any = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=os.environ["JURISNEXO_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["JURISNEXO_S3_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style": "path" if force_path_style else "virtual"}),
    )
    return S3ObjectStore(client=client, config=config, is_not_found=is_s3_not_found)


def assigned_records(*, inventory_path: Path, shard_index: int, shard_count: int) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    assigned_index = 0
    with inventory_path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("TC inventory JSONL contains a non-object record")
            if assigned_index % shard_count == shard_index:
                sentence_id = str(value.get("source_identifier") or "").strip()
                detail_url = str(value.get("detail_url") or "").strip()
                if not sentence_id.startswith("TC/") or not detail_url.startswith("https://"):
                    raise ValueError("TC inventory record lacks a stable identifier or detail URL")
                records.append({"source_identifier": sentence_id, "detail_url": detail_url})
            assigned_index += 1
    return records


def main() -> None:
    require_environment()
    shard_index = int(os.environ["TC_BACKFILL_SHARD_INDEX"])
    shard_count = int(os.environ["TC_BACKFILL_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid TC backfill shard coordinates")
    output_dir = Path(os.environ["TC_BACKFILL_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_telemetry(shard_index=shard_index, shard_count=shard_count)
    tracer = trace.get_tracer("jurisnexo.tc.backfill")
    fetcher = BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)
    object_store = build_object_store()
    records = assigned_records(
        inventory_path=Path(os.environ["TC_INVENTORY_FILE"]),
        shard_index=shard_index,
        shard_count=shard_count,
    )

    acquired = 0
    skipped_verified = 0
    repaired_storage = 0
    bytes_acquired = 0
    failures: list[dict[str, str]] = []
    with tracer.start_as_current_span("tc.backfill.shard") as root:
        root.set_attribute("tc.shard.index", shard_index)
        root.set_attribute("tc.shard.count", shard_count)
        root.set_attribute("tc.shard.candidate_count", len(records))
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            catalog = PostgresOfficialArtifactCatalog(
                connection=connection,
                storage_bucket=os.environ["JURISNEXO_S3_BUCKET"],
            )
            registered = PostgresRegisteredArtifactInventory(connection=connection).observations_for(
                "constitutional_court"
            )
            current = {
                (item.source_identifier, item.document_url): item.sha256 for item in registered
            }

            for index, record in enumerate(records):
                sentence_id = record["source_identifier"]
                detail_url = record["detail_url"]
                try:
                    with tracer.start_as_current_span("tc.backfill.item") as span:
                        span.set_attribute("tc.shard.item_index", index)
                        span.set_attribute("source_identifier", sentence_id)

                        detail_html = fetcher.get_bytes(detail_url).decode("utf-8", errors="replace")
                        document_url = discover_pdf_link(
                            html=detail_html,
                            page_url=detail_url,
                            allowed_host="tribunalsitestorage.blob.core.windows.net",
                        )
                        candidate = OfficialDocumentCandidate(
                            source="constitutional_court",
                            source_identifier=sentence_id,
                            discovery_url=detail_url,
                            document_url=document_url,
                            collection="decisions",
                        )

                        existing_digest = current.get((sentence_id, document_url))
                        if existing_digest is not None:
                            key = object_key_for(
                                source="constitutional_court",
                                collection="decisions",
                                sha256=existing_digest,
                            )
                            if object_store.exists(key):
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
                            raise RuntimeError("TC backfill item did not produce exactly one artifact")
                        artifact = artifacts[0]
                        current[(sentence_id, document_url)] = artifact.sha256
                        acquired += 1
                        bytes_acquired += artifact.byte_count
                        span.set_attribute("artifact.sha256_prefix", artifact.sha256[:12])
                except Exception as exc:
                    failure = {
                        "source_identifier": sentence_id,
                        "detail_url": detail_url,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2000],
                    }
                    failures.append(failure)
                    print(
                        json.dumps({"event": "tc_backfill_item_failed", **failure}, ensure_ascii=False),
                        flush=True,
                    )

                if (index + 1) % 100 == 0 or index + 1 == len(records):
                    print(
                        json.dumps(
                            {
                                "event": "tc_backfill_progress",
                                "shard_index": shard_index,
                                "processed": index + 1,
                                "total": len(records),
                                "acquired": acquired,
                                "skipped_verified": skipped_verified,
                                "storage_repairs": repaired_storage,
                                "failures": len(failures),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )

        summary = {
            "status": "PASS" if not failures else "INCOMPLETE",
            "shard_index": shard_index,
            "shard_count": shard_count,
            "candidate_count": len(records),
            "acquired_or_repaired_count": acquired,
            "skipped_verified_count": skipped_verified,
            "storage_repair_count": repaired_storage,
            "failure_count": len(failures),
            "bytes_acquired": bytes_acquired,
        }
        (output_dir / f"backfill-{shard_index:02d}-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        with (output_dir / f"backfill-{shard_index:02d}-failures.jsonl").open(
            "w", encoding="utf-8"
        ) as handle:
            for failure in failures:
                handle.write(json.dumps(failure, ensure_ascii=False, sort_keys=True) + "\n")
        root.set_attribute("tc.shard.acquired_count", acquired)
        root.set_attribute("tc.shard.skipped_verified_count", skipped_verified)
        root.set_attribute("tc.shard.failure_count", len(failures))
        root.set_attribute("tc.shard.bytes_acquired", bytes_acquired)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]
    if failures:
        raise RuntimeError(f"TC shard {shard_index} completed with {len(failures)} failed documents")


if __name__ == "__main__":
    main()
