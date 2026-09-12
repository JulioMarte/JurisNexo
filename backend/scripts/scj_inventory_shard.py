from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from playwright.sync_api import APIRequestContext, sync_playwright

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
PAGE_SIZE = 10
Surface = Literal["decisions", "historical", "bulletins"]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def configure_telemetry(surface: Surface) -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-inventory",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
                "jurisnexo.surface": surface,
                "jurisnexo.shard.index": int(os.environ["SCJ_SHARD_INDEX"]),
                "jurisnexo.shard.count": int(os.environ["SCJ_SHARD_COUNT"]),
            }
        )
    )
    if _env_flag("JURISNEXO_OTEL_CONSOLE", True):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def datatables_form(*, start: int, historical: bool = False) -> dict[str, str]:
    column_count = 3 if historical else 4
    fields: dict[str, str] = {"draw": "1"}
    for column in range(column_count):
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
            "Ano": "",
            "Mes": "",
            "Contenido": "",
        }
    )
    if not historical:
        fields.update({"IdTribunal": "", "Materia": "", "IdTipoDocumento": "1"})
    return fields


def post_json(request: APIRequestContext, *, path: str, form: dict[str, str]) -> dict[str, Any]:
    response = request.post(
        f"{TARGET.rstrip('/')}{path}",
        form=form,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": TARGET,
        },
        timeout=90_000,
    )
    if response.status != 200:
        raise RuntimeError(f"SCJ {path} returned HTTP {response.status}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"SCJ {path} response is not an object")
    return payload


def fetch_page(
    request: APIRequestContext, *, surface: Surface, start: int
) -> tuple[int, list[dict[str, Any]]]:
    if surface == "decisions":
        payload = post_json(request, path="/Home/GetExpedientes", form=datatables_form(start=start))
    elif surface == "historical":
        payload = post_json(
            request,
            path="/Home/GetBoletinesHistorico",
            form=datatables_form(start=start, historical=True),
        )
    else:
        raise ValueError("bulletins do not use server-side paging")
    rows = payload.get("data", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError(f"SCJ {surface} data is not a list of objects")
    return int(payload.get("recordsFiltered", 0)), rows


def normalize_bulletin_url(raw_value: object) -> tuple[str | None, str, dict[str, Any]]:
    if raw_value is None:
        return None, "not_published", {"document_url_state": "source_null"}
    raw = str(raw_value).strip()
    if not raw or raw.casefold() == "null":
        return None, "not_published", {
            "document_url_state": "source_null_text",
            "raw_document_url": raw,
        }
    if raw.startswith("https://"):
        return raw, "available", {}
    if raw.startswith("NULLhttps://"):
        return raw[4:], "available", {
            "document_url_normalization": "stripped_literal_NULL_prefix",
            "raw_document_url": raw,
        }
    raise ValueError(f"unsupported SCJ bulletin document URL shape: {raw!r}")


def record_identity(surface: Surface, row: dict[str, Any]) -> tuple[str, str | None, str, dict[str, Any]]:
    if surface == "decisions":
        identifier = str(row.get("idExpediente") or "").strip()
        guid = str(row.get("guidBlob") or "").strip()
        url = str(row.get("urlBlob") or "").strip()
        if not identifier or not url.startswith("https://"):
            raise ValueError("SCJ decisions row lacks a stable identifier or HTTPS PDF URL")
        return f"decisions\t{identifier}\t{guid}\t{url}", url, "available", {}
    if surface == "historical":
        identifier = f"{row.get('ano', '')}-{row.get('mes', '')}-{row.get('partes', '')}".strip()
        url = str(row.get("rutaDoc") or "").strip()
        if not identifier or not url.startswith("https://"):
            raise ValueError("SCJ historical row lacks a stable identifier or HTTPS PDF URL")
        return f"historical\t{identifier}\t\t{url}", url, "available", {}
    body_id = str(row.get("idCuerpo") or "").strip()
    header_id = str(row.get("idCabecera") or "").strip()
    if not body_id:
        raise ValueError("SCJ bulletin row lacks idCuerpo")
    url, availability, notes = normalize_bulletin_url(row.get("urlCuerpo"))
    return f"bulletins\t{header_id}\t{body_id}", url, availability, notes


def write_record(
    output: Any,
    *,
    surface: Surface,
    shard_index: int,
    coordinate: str,
    row: dict[str, Any],
    digest: Any,
) -> None:
    key, document_url, availability, notes = record_identity(surface, row)
    digest.update(key.encode("utf-8"))
    digest.update(b"\n")
    output.write(
        json.dumps(
            {
                "surface": surface,
                "shard_index": shard_index,
                "coordinate": coordinate,
                "_stable_key": key,
                "_document_url": document_url,
                "_artifact_availability": availability,
                "_normalization_notes": notes,
                "row": row,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    output.write("\n")


def write_rejected_row(
    path: Path,
    *,
    surface: Surface,
    shard_index: int,
    coordinate: str,
    row: dict[str, Any],
    error: Exception,
) -> None:
    with path.open("a", encoding="utf-8") as rejected:
        rejected.write(
            json.dumps(
                {
                    "surface": surface,
                    "shard_index": shard_index,
                    "coordinate": coordinate,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "row": row,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )


def main() -> None:
    surface_value = os.environ.get("SCJ_SURFACE", "decisions")
    if surface_value not in {"decisions", "historical", "bulletins"}:
        raise ValueError(f"unknown SCJ surface: {surface_value}")
    surface: Surface = surface_value  # type: ignore[assignment]
    shard_index = int(os.environ["SCJ_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_SHARD_COUNT"])
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid SCJ shard coordinates")
    output_dir = Path(os.environ["SCJ_SHARD_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_telemetry(surface)
    tracer = trace.get_tracer("jurisnexo.scj.inventory")
    output_path = output_dir / f"{surface}-shard-{shard_index:02d}.jsonl"
    rejected_path = output_dir / f"{surface}-shard-{shard_index:02d}-rejected.jsonl"
    if rejected_path.exists():
        rejected_path.unlink()
    key_digest = hashlib.sha256()
    row_count = 0
    expected_total: int | None = None
    total_pages: int | None = None
    all_years: list[int] = []
    processed_years: list[int] = []

    with tracer.start_as_current_span("scj.inventory.shard") as root:
        root.set_attribute("scj.surface", surface)
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
            page.wait_for_timeout(2_000)
            with output_path.open("w", encoding="utf-8") as output:
                if surface in {"decisions", "historical"}:
                    expected_total, first_rows = fetch_page(context.request, surface=surface, start=0)
                    if expected_total <= 0 or not first_rows:
                        raise RuntimeError(f"SCJ {surface} initialization returned no records")
                    total_pages = math.ceil(expected_total / PAGE_SIZE)
                    root.set_attribute("scj.inventory.expected_rows", expected_total)
                    root.set_attribute("scj.inventory.total_pages", total_pages)
                    for page_index in range(shard_index, total_pages, shard_count):
                        start = page_index * PAGE_SIZE
                        with tracer.start_as_current_span("scj.inventory.page") as span:
                            observed_total, rows = fetch_page(context.request, surface=surface, start=start)
                            if observed_total != expected_total:
                                raise RuntimeError(
                                    f"SCJ {surface} changed during snapshot: expected={expected_total}, observed={observed_total}, start={start}"
                                )
                            if not rows:
                                raise RuntimeError(f"SCJ {surface} returned an empty page before total at start={start}")
                            for offset, row in enumerate(rows):
                                coordinate = f"start={start};offset={offset}"
                                try:
                                    write_record(output, surface=surface, shard_index=shard_index, coordinate=coordinate, row=row, digest=key_digest)
                                except ValueError as exc:
                                    write_rejected_row(rejected_path, surface=surface, shard_index=shard_index, coordinate=coordinate, row=row, error=exc)
                                    raise
                                row_count += 1
                            span.set_attribute("scj.page.row_count", len(rows))
                else:
                    year_options = page.locator("#cbAno option").evaluate_all(
                        "els => els.map(o => o.value).filter(v => /^\\d{4}$/.test(v)).map(Number)"
                    )
                    all_years = sorted({int(year) for year in year_options})
                    if not all_years:
                        raise RuntimeError("SCJ bulletin year selector exposed no years")
                    processed_years = [year for index, year in enumerate(all_years) if index % shard_count == shard_index]
                    for year in processed_years:
                        with tracer.start_as_current_span("scj.inventory.year") as span:
                            payload = post_json(context.request, path="/Home/GetBoletines", form={"Ano": str(year), "Mes": ""})
                            rows = payload.get("data", [])
                            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                                raise TypeError("SCJ bulletin data is not a list of objects")
                            for offset, row in enumerate(rows):
                                coordinate = f"year={year};offset={offset}"
                                try:
                                    write_record(output, surface=surface, shard_index=shard_index, coordinate=coordinate, row=row, digest=key_digest)
                                except ValueError as exc:
                                    write_rejected_row(rejected_path, surface=surface, shard_index=shard_index, coordinate=coordinate, row=row, error=exc)
                                    raise
                                row_count += 1
                            span.set_attribute("scj.year.row_count", len(rows))
            browser.close()

        summary = {
            "surface": surface,
            "shard_index": shard_index,
            "shard_count": shard_count,
            "expected_total_rows": expected_total,
            "total_pages": total_pages,
            "captured_rows": row_count,
            "stable_key_stream_sha256": key_digest.hexdigest(),
            "page_size": PAGE_SIZE,
            "all_years": all_years,
            "processed_years": processed_years,
        }
        (output_dir / f"{surface}-shard-{shard_index:02d}-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        root.set_attribute("scj.inventory.captured_rows", row_count)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
