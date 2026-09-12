from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.official_corpus import TC_SENTENCES_URL, discover_tc_detail_pages

OUTPUT_DIR = Path(os.environ.get("TC_INVENTORY_OUTPUT", "tc-inventory-output"))


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def configure_telemetry() -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-tc-inventory",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
            }
        )
    )
    if _env_flag("JURISNEXO_OTEL_CONSOLE", False):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_telemetry()
    tracer = trace.get_tracer("jurisnexo.tc.inventory")
    fetcher = BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)

    with tracer.start_as_current_span("tc.inventory.snapshot") as span:
        html = fetcher.get_bytes(TC_SENTENCES_URL).decode("utf-8", errors="replace")
        entries = discover_tc_detail_pages(html=html, listing_url=TC_SENTENCES_URL)
        if not entries:
            raise RuntimeError("TC official listing returned no sentence detail pages")
        sentence_ids = [sentence_id for sentence_id, _ in entries]
        if len(sentence_ids) != len(set(sentence_ids)):
            raise RuntimeError("TC inventory contains duplicate sentence identifiers")

        digest = hashlib.sha256()
        inventory_path = OUTPUT_DIR / "tc-documents.inventory.jsonl"
        with inventory_path.open("w", encoding="utf-8") as output:
            for sentence_id, detail_url in entries:
                record = {
                    "source": "constitutional_court",
                    "source_identifier": sentence_id,
                    "detail_url": detail_url,
                    "collection": "decisions",
                }
                line = json.dumps(record, ensure_ascii=False, sort_keys=True)
                digest.update(line.encode("utf-8"))
                digest.update(b"\n")
                output.write(line)
                output.write("\n")

        summary = {
            "status": "COMPLETE",
            "source": "constitutional_court",
            "official_listing_url": TC_SENTENCES_URL,
            "unique_document_record_count": len(entries),
            "inventory_sha256": digest.hexdigest(),
            "enumeration_basis": (
                "Official Tribunal Constitucional sentence listing requested with size=999999; "
                "every unique TC/* detail-page identifier present in the returned HTML is retained"
            ),
        }
        (OUTPUT_DIR / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        span.set_attribute("tc.inventory.document_count", len(entries))

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
