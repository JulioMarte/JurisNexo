from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from playwright.sync_api import APIRequestContext, sync_playwright

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
PAGE_SIZE = 10
Surface = Literal["decisions", "historical"]


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


def datatables_form(*, start: int, year: int, historical: bool) -> dict[str, str]:
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
            "Ano": str(year),
            "Mes": "",
            "Contenido": "",
        }
    )
    if not historical:
        fields.update({"IdTribunal": "", "Materia": "", "IdTipoDocumento": "1"})
    return fields


def post_json(
    request: APIRequestContext,
    *,
    path: str,
    form: dict[str, str],
) -> dict[str, Any]:
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
    request: APIRequestContext,
    *,
    surface: Surface,
    year: int,
    start: int,
) -> tuple[int, list[dict[str, Any]]]:
    path = "/Home/GetExpedientes" if surface == "decisions" else "/Home/GetBoletinesHistorico"
    payload = post_json(
        request,
        path=path,
        form=datatables_form(
            start=start,
            year=year,
            historical=surface == "historical",
        ),
    )
    rows = payload.get("data", [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError(f"SCJ {surface} data is not a list of objects")
    return int(payload.get("recordsFiltered", 0)), rows


def stable_identity(surface: Surface, row: dict[str, Any]) -> tuple[str, str]:
    if surface == "decisions":
        expediente_id = str(row.get("idExpediente") or "").strip()
        guid = str(row.get("guidBlob") or "").strip()
        url = str(row.get("urlBlob") or "").strip()
        if not expediente_id or not url.startswith("https://"):
            raise ValueError("SCJ decision row lacks idExpediente or HTTPS PDF URL")
        return f"decisions\t{expediente_id}\t{guid}\t{url}", url

    url = str(row.get("rutaDoc") or "").strip()
    year = str(row.get("ano") or "").strip()
    month = str(row.get("mes") or "").strip()
    parties = " ".join(str(row.get("partes") or "").split())
    if not url.startswith("https://") or not (year or month or parties):
        raise ValueError("SCJ historical row lacks stable metadata or HTTPS PDF URL")
    return f"historical\t{year}\t{month}\t{parties}\t{url}", url


def main() -> None:
    surface_value = os.environ["SCJ_SURFACE"].strip()
    if surface_value not in {"decisions", "historical"}:
        raise ValueError(f"unsupported surface: {surface_value}")
    surface: Surface = surface_value  # type: ignore[assignment]
    shard_index = int(os.environ["SCJ_SHARD_INDEX"])
    shard_count = int(os.environ["SCJ_SHARD_COUNT"])
    year_min = int(os.environ.get("SCJ_YEAR_MIN", "1994"))
    year_max = int(os.environ.get("SCJ_YEAR_MAX", "2026"))
    if year_min > year_max:
        raise ValueError("SCJ_YEAR_MIN must be <= SCJ_YEAR_MAX")
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard coordinates")

    output_dir = Path(os.environ["SCJ_SHARD_OUTPUT"])
    output_dir.mkdir(parents=True, exist_ok=True)
    assigned_years = [
        year
        for offset, year in enumerate(range(year_min, year_max + 1))
        if offset % shard_count == shard_index
    ]
    output_path = output_dir / f"{surface}-years-shard-{shard_index:02d}.jsonl"
    summary_path = output_dir / f"{surface}-years-shard-{shard_index:02d}-summary.json"
    digest = hashlib.sha256()
    captured = 0
    year_reports: dict[str, object] = {}

    _event(
        "scj.year_inventory.started",
        surface=surface,
        shard_index=shard_index,
        shard_count=shard_count,
        assigned_years=assigned_years,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        navigation = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
        if navigation is None or navigation.status != 200:
            raise RuntimeError("SCJ portal bootstrap failed")
        page.select_option("#cbTipoDocumento", "1")
        page.wait_for_timeout(1_000)

        with output_path.open("w", encoding="utf-8") as output:
            for year in assigned_years:
                expected_total, first_rows = fetch_page(
                    context.request,
                    surface=surface,
                    year=year,
                    start=0,
                )
                _event(
                    "scj.year_inventory.year_started",
                    surface=surface,
                    year=year,
                    expected_total=expected_total,
                )
                if expected_total == 0:
                    year_reports[str(year)] = {
                        "official_record_count": 0,
                        "captured_position_count": 0,
                        "unique_stable_key_count": 0,
                    }
                    continue
                if not first_rows:
                    raise RuntimeError(
                        f"SCJ {surface} year {year} reports {expected_total} rows but first page is empty"
                    )

                total_pages = math.ceil(expected_total / PAGE_SIZE)
                position_keys: dict[int, set[str]] = {}
                stable_keys: set[str] = set()
                raw_observations = 0

                for page_index in range(total_pages):
                    start = page_index * PAGE_SIZE
                    observed_total, rows = fetch_page(
                        context.request,
                        surface=surface,
                        year=year,
                        start=start,
                    )
                    if observed_total != expected_total:
                        raise RuntimeError(
                            f"SCJ {surface} year {year} changed during snapshot: "
                            f"expected={expected_total} observed={observed_total}"
                        )
                    if not rows:
                        raise RuntimeError(
                            f"SCJ {surface} year {year} empty page before total at start={start}"
                        )
                    for offset, row in enumerate(rows):
                        key, document_url = stable_identity(surface, row)
                        raw_position = row.get("linea")
                        if not isinstance(raw_position, int):
                            raise ValueError(
                                f"SCJ {surface} year {year} row lacks integer linea"
                            )
                        position_keys.setdefault(raw_position, set()).add(key)
                        stable_keys.add(key)
                        record = {
                            "surface": surface,
                            "year": year,
                            "shard_index": shard_index,
                            "coordinate": f"year={year};start={start};offset={offset}",
                            "_stable_key": key,
                            "_document_url": document_url,
                            "_artifact_availability": "available",
                            "row": row,
                        }
                        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
                        digest.update(line.encode("utf-8"))
                        digest.update(b"\n")
                        output.write(line + "\n")
                        raw_observations += 1
                        captured += 1

                ambiguous = {
                    position: sorted(keys)
                    for position, keys in position_keys.items()
                    if len(keys) > 1
                }
                if ambiguous:
                    raise RuntimeError(
                        f"SCJ {surface} year {year} conflicting stable keys per linea: "
                        f"{dict(list(sorted(ambiguous.items()))[:10])}"
                    )
                if len(position_keys) != expected_total:
                    raise RuntimeError(
                        f"SCJ {surface} year {year} incomplete position coverage: "
                        f"expected={expected_total} observed={len(position_keys)}"
                    )
                year_reports[str(year)] = {
                    "official_record_count": expected_total,
                    "captured_position_count": len(position_keys),
                    "raw_observation_count": raw_observations,
                    "unique_stable_key_count": len(stable_keys),
                }
                _event(
                    "scj.year_inventory.year_completed",
                    surface=surface,
                    year=year,
                    expected_total=expected_total,
                    unique_stable_key_count=len(stable_keys),
                )
        browser.close()

    summary = {
        "surface": surface,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "year_min": year_min,
        "year_max": year_max,
        "assigned_years": assigned_years,
        "captured_raw_records": captured,
        "inventory_sha256": digest.hexdigest(),
        "year_reports": year_reports,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _event(
        "scj.year_inventory.completed",
        surface=surface,
        shard_index=shard_index,
        captured_raw_records=captured,
    )


if __name__ == "__main__":
    main()
