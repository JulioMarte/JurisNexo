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
from playwright.sync_api import sync_playwright

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.official_corpus import OfficialDocumentCandidate, acquire_candidates
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, S3ObjectStoreConfig
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog
from jurisnexo.corpus.artifact_inventory import PostgresRegisteredArtifactInventory

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
ENDPOINT = "https://consultasentenciascj.poderjudicial.gob.do/Home/GetExpedientes"
OUT = Path(os.environ.get("SCJ_CANARY_OUTPUT", "scj-canary-output"))
REQUIRED_ENV = (
    "DATABASE_URL",
    "JURISNEXO_S3_BUCKET",
    "JURISNEXO_S3_ENDPOINT_URL",
    "JURISNEXO_S3_REGION",
    "JURISNEXO_S3_ACCESS_KEY_ID",
    "JURISNEXO_S3_SECRET_ACCESS_KEY",
)


def require_environment() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing required live-backfill configuration: " + ", ".join(missing))


def configure_telemetry() -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-backfill-canary",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def datatables_form(*, start: int, length: int) -> dict[str, str]:
    fields: dict[str, str] = {"draw": "1"}
    for column in range(4):
        prefix = f"columns[{column}]"
        fields.update(
            {
                f"{prefix}[data]": "",
                f"{prefix}[name]": "",
                f"{prefix}[searchable]": "true",
                f"{prefix}[orderable]": "false",
                f"{prefix}[search][value]": "",
                f"{prefix}[search][regex]": "false",
            }
        )
    fields.update(
        {
            "start": str(start),
            "length": str(length),
            "search[value]": "",
            "search[regex]": "false",
            "IdTribunal": "",
            "Materia": "",
            "Ano": "",
            "Mes": "",
            "IdTipoDocumento": "1",
            "Contenido": "",
        }
    )
    return fields


def candidates_from_live_portal(*, limit: int) -> tuple[OfficialDocumentCandidate, ...]:
    tracer = trace.get_tracer("jurisnexo.scj.canary")
    with tracer.start_as_current_span("scj.inventory.canary") as span:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            navigation = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
            if navigation is None or navigation.status != 200:
                raise RuntimeError("SCJ portal bootstrap failed")
            page.select_option("#cbTipoDocumento", "1")
            page.wait_for_timeout(3_000)
            response = context.request.post(
                ENDPOINT,
                form=datatables_form(start=0, length=max(10, limit)),
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": TARGET,
                },
                timeout=90_000,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("SCJ inventory response is not an object")
            rows = payload.get("data", [])
            if not isinstance(rows, list):
                raise TypeError("SCJ inventory data is not a list")
            total = int(payload.get("recordsFiltered", 0))
            if total <= 0 or not rows:
                raise RuntimeError("SCJ inventory unexpectedly returned no decisions")

            candidates: list[OfficialDocumentCandidate] = []
            for row in rows[:limit]:
                if not isinstance(row, dict):
                    raise TypeError("SCJ inventory row is not an object")
                document_url = str(row.get("urlBlob") or "").strip()
                expediente_id = str(row.get("idExpediente") or "").strip()
                guid_blob = str(row.get("guidBlob") or "").strip()
                if not document_url.startswith("https://") or not expediente_id:
                    raise ValueError("SCJ inventory row lacks stable PDF URL or expediente id")
                host = urlparse(document_url).hostname or ""
                if host.casefold() not in OFFICIAL_SOURCE_HOSTS:
                    raise ValueError(f"SCJ PDF uses non-allowlisted host: {host}")
                source_identifier = f"expediente:{expediente_id}"
                if guid_blob:
                    source_identifier += f":{guid_blob}"
                candidates.append(
                    OfficialDocumentCandidate(
                        source="supreme_court",
                        source_identifier=source_identifier,
                        discovery_url=TARGET,
                        document_url=document_url,
                    )
                )
            browser.close()

        span.set_attribute("scj.inventory.total_decisions", total)
        span.set_attribute("scj.canary.candidate_count", len(candidates))
        return tuple(candidates)


def is_s3_not_found(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    error = exc.response.get("Error", {})
    code = str(error.get("Code", ""))
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
    addressing_style = "path" if force_path_style else "virtual"
    client: Any = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=os.environ["JURISNEXO_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["JURISNEXO_S3_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style": addressing_style}),
    )
    return S3ObjectStore(client=client, config=config, is_not_found=is_s3_not_found)


def main() -> None:
    require_environment()
    OUT.mkdir(parents=True, exist_ok=True)
    configure_telemetry()
    tracer = trace.get_tracer("jurisnexo.scj.canary")
    limit = int(os.environ.get("SCJ_CANARY_LIMIT", "3"))
    if limit < 1 or limit > 10:
        raise ValueError("SCJ_CANARY_LIMIT must be between 1 and 10")

    with tracer.start_as_current_span("scj.backfill.canary") as root:
        candidates = candidates_from_live_portal(limit=limit)
        object_store = build_object_store()
        fetcher = BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            catalog = PostgresOfficialArtifactCatalog(
                connection=connection,
                storage_bucket=os.environ["JURISNEXO_S3_BUCKET"],
            )
            artifacts = acquire_candidates(
                candidates=candidates,
                fetcher=fetcher,
                object_store=object_store,
                artifact_catalog=catalog,
            )
            inventory = PostgresRegisteredArtifactInventory(connection=connection)
            observations = inventory.observations_for("supreme_court")
            current = {
                (item.source_identifier, item.document_url): item.sha256 for item in observations
            }
            missing_catalog = [
                candidate.source_identifier
                for candidate in candidates
                if (candidate.source_identifier, candidate.document_url) not in current
            ]
            missing_objects = [
                artifact.candidate.source_identifier
                for artifact in artifacts
                if not object_store.exists(artifact.object_key)
            ]
            if missing_catalog or missing_objects:
                raise RuntimeError(
                    "SCJ canary verification failed: "
                    f"missing_catalog={missing_catalog}, missing_objects={missing_objects}"
                )

        summary = {
            "status": "PASS",
            "candidate_count": len(candidates),
            "acquired_count": len(artifacts),
            "already_present_count": sum(item.already_present for item in artifacts),
            "verified_catalog_count": len(candidates) - len(missing_catalog),
            "verified_storage_count": len(artifacts) - len(missing_objects),
            "object_prefix": "official/supreme_court/",
        }
        (OUT / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        root.set_attribute("scj.canary.candidate_count", len(candidates))
        root.set_attribute("scj.canary.acquired_count", len(artifacts))
        root.set_attribute("scj.canary.already_present_count", summary["already_present_count"])

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
