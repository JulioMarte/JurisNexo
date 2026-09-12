from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    "SCJ_INVENTORY_FILE",
    "SCJ_BACKFILL_SHARD_INDEX",
    "SCJ_BACKFILL_SHARD_COUNT",
    "SCJ_BACKFILL_OUTPUT",
)


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
    force_path_style = os.environ.get("JURISNEXO_S3_FORCE_PATH_STYLE", "true").casefold() not in {
        "0",
        "false",
        "no",
    }
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


def candidate_from_record(record: dict[str, Any]) -> OfficialDocumentCandidate:
    row = record.get("row")
    if not isinstance(row, dict):
        raise TypeError("SCJ inventory record is missing its row object")
    document_url = str(row.get("urlBlob") or "").strip()
    expediente_id = str(row.get("idExpediente") or "").strip()
    guid_blob = str(row.get("guidBlob") or "").strip()
    if not expediente_id or not document_url.startswith("https://"):
        raise ValueError("SCJ inventory row lacks idExpediente or HTTPS urlBlob")
    host = (urlparse(document_url).hostname or "").casefold()
    if host not in OFFICIAL_SOURCE_HOSTS:
        raise ValueError(f"SCJ inventory references non-allowlisted PDF host: {host}")
    identifier = f"expediente:{expediente_id}"
    if guid_blob:
        identifier += f":{guid_blob}"
    return OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier=identifier,
        discovery_url="https://consultasentenciascj.poderjudicial.gob.do/",
        document_url=document_url,
    )


def assigned_candidates(
    *, inventory_path: Path, shard_index: int, shard_count: int
) -> list[OfficialDocumentCandidate]:
    candidates: list[OfficialDocumentCandidate] = []
    with inventory_path.open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            if not line.strip() or index % shard_count != shard_index:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("SCJ inventory JSONL contains a non-object record")
            candidates.append(candidate_from_record(record))
    return candidates


def main() -> None:
    require_environment()
    shard_index = int(os.environ["SCJ_BACKFILL_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_BACKFILL_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid backfill shard coordinates")
    output_dir = Path(os.environ["SCJ_BACKFILL_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_telemetry(shard_index=shard_index, shard_count=shard_count)
    tracer = trace.get_tracer("jurisnexo.scj.backfill")
    object_store = build_object_store()
    fetcher = BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)
    candidates = assigned_candidates(
        inventory_path=Path(os.environ["SCJ_INVENTORY_FILE"]),
        shard_index=shard_index,
        shard_count=shard_count,
    )

    acquired = 0
    skipped_verified = 0
    repaired_storage = 0
    with tracer.start_as_current_span("scj.backfill.shard") as root:
        root.set_attribute("scj.shard.index", shard_index)
        root.set_attribute("scj.shard.count", shard_count)
        root.set_attribute("scj.shard.candidate_count", len(candidates))
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            catalog = PostgresOfficialArtifactCatalog(
                connection=connection,
                storage_bucket=os.environ["JURISNEXO_S3_BUCKET"],
            )
            registered = PostgresRegisteredArtifactInventory(connection=connection).observations_for(
                "supreme_court"
            )
            current = {
                (item.source_identifier, item.document_url): item.sha256 for item in registered
            }
            for index, candidate in enumerate(candidates):
                with tracer.start_as_current_span("scj.backfill.item") as span:
                    span.set_attribute("scj.shard.item_index", index)
                    span.set_attribute("source_identifier", candidate.source_identifier)
                    existing_digest = current.get(
                        (candidate.source_identifier, candidate.document_url)
                    )
                    if existing_digest is not None:
                        key = object_key_for(source="supreme_court", sha256=existing_digest)
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
                        raise RuntimeError("SCJ backfill item did not produce exactly one artifact")
                    artifact = artifacts[0]
                    current[(candidate.source_identifier, candidate.document_url)] = artifact.sha256
                    acquired += 1
                    span.set_attribute("artifact.sha256_prefix", artifact.sha256[:12])

        summary = {
            "status": "PASS",
            "shard_index": shard_index,
            "shard_count": shard_count,
            "candidate_count": len(candidates),
            "acquired_or_repaired_count": acquired,
            "skipped_verified_count": skipped_verified,
            "storage_repair_count": repaired_storage,
        }
        (output_dir / f"backfill-{shard_index:02d}-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        root.set_attribute("scj.shard.acquired_count", acquired)
        root.set_attribute("scj.shard.skipped_verified_count", skipped_verified)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
