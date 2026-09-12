from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from playwright.sync_api import APIRequestContext, sync_playwright

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
ENDPOINT = "https://consultasentenciascj.poderjudicial.gob.do/Home/GetExpedientes"
PAGE_SIZE = 10


def configure_telemetry() -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-inventory",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
                "jurisnexo.shard.index": int(os.environ["SCJ_SHARD_INDEX"]),
                "jurisnexo.shard.count": int(os.environ["SCJ_SHARD_COUNT"]),
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def datatables_form(*, start: int) -> dict[str, str]:
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
            "length": str(PAGE_SIZE),
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


def fetch_page(request: APIRequestContext, *, start: int) -> tuple[int, list[dict[str, Any]]]:
    response = request.post(
        ENDPOINT,
        form=datatables_form(start=start),
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": TARGET,
        },
        timeout=90_000,
    )
    if response.status != 200:
        raise RuntimeError(f"SCJ inventory page start={start} returned HTTP {response.status}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("SCJ inventory response is not an object")
    rows = payload.get("data", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError("SCJ inventory data is not a list of objects")
    total = int(payload.get("recordsFiltered", 0))
    return total, rows


def stable_row_key(row: dict[str, Any]) -> str:
    expediente = str(row.get("idExpediente") or "").strip()
    guid = str(row.get("guidBlob") or "").strip()
    url = str(row.get("urlBlob") or "").strip()
    if not expediente or not url.startswith("https://"):
        raise ValueError("SCJ decision row lacks idExpediente or HTTPS urlBlob")
    return f"{expediente}\t{guid}\t{url}"


def main() -> None:
    shard_index = int(os.environ["SCJ_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid SCJ shard coordinates")
    output_dir = Path(os.environ["SCJ_SHARD_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_telemetry()
    tracer = trace.get_tracer("jurisnexo.scj.inventory")

    output_path = output_dir / f"shard-{shard_index:02d}.jsonl"
    key_digest = hashlib.sha256()
    row_count = 0

    with tracer.start_as_current_span("scj.inventory.shard") as root:
        root.set_attribute("scj.shard.index", shard_index)
        root.set_attribute("scj.shard.count", shard_count)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            navigation = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
            if navigation is None or navigation.status != 200:
                raise RuntimeError("SCJ portal bootstrap failed")
            page.select_option("#cbTipoDocumento", "1")
            page.wait_for_timeout(3_000)

            total, first_rows = fetch_page(context.request, start=0)
            if total <= 0 or not first_rows:
                raise RuntimeError("SCJ inventory initialization returned no decisions")
            total_pages = math.ceil(total / PAGE_SIZE)
            root.set_attribute("scj.inventory.expected_rows", total)
            root.set_attribute("scj.inventory.total_pages", total_pages)

            with output_path.open("w", encoding="utf-8") as output:
                for page_index in range(shard_index, total_pages, shard_count):
                    start = page_index * PAGE_SIZE
                    with tracer.start_as_current_span("scj.inventory.page") as span:
                        span.set_attribute("scj.page.index", page_index)
                        span.set_attribute("scj.page.start", start)
                        observed_total, rows = fetch_page(context.request, start=start)
                        if observed_total != total:
                            raise RuntimeError(
                                "SCJ inventory changed during snapshot: "
                                f"expected={total}, observed={observed_total}, start={start}"
                            )
                        expected_page_size = min(PAGE_SIZE, total - start)
                        if len(rows) != expected_page_size:
                            raise RuntimeError(
                                f"SCJ page start={start} expected {expected_page_size} rows, "
                                f"got {len(rows)}"
                            )
                        for offset, row in enumerate(rows):
                            key = stable_row_key(row)
                            key_digest.update(key.encode("utf-8"))
                            key_digest.update(b"\n")
                            record = {
                                "_page_index": page_index,
                                "_start": start,
                                "_offset": offset,
                                "_stable_key": key,
                                "row": row,
                            }
                            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                            output.write("\n")
                            row_count += 1
                        span.set_attribute("scj.page.row_count", len(rows))

            browser.close()

        summary = {
            "shard_index": shard_index,
            "shard_count": shard_count,
            "expected_total_rows": total,
            "total_pages": total_pages,
            "captured_rows": row_count,
            "stable_key_stream_sha256": key_digest.hexdigest(),
            "page_size": PAGE_SIZE,
        }
        (output_dir / f"shard-{shard_index:02d}-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        root.set_attribute("scj.inventory.captured_rows", row_count)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
