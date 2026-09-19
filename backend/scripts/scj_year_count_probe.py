from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
YEAR_MIN = int(os.environ.get("SCJ_YEAR_MIN", "1994"))
YEAR_MAX = int(os.environ.get("SCJ_YEAR_MAX", "2026"))
OUT = Path(os.environ.get("SCJ_YEAR_PROBE_OUTPUT", "scj-year-probe-output"))


def form(*, year: int, historical: bool) -> dict[str, str]:
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
            "start": "0",
            "length": "10",
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, int]] = {"decisions": {}, "historical": {}}
    samples: dict[str, dict[str, Any]] = {"decisions": {}, "historical": {}}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        nav = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
        if nav is None or nav.status != 200:
            raise RuntimeError("SCJ portal bootstrap failed")
        page.select_option("#cbTipoDocumento", "1")
        page.wait_for_timeout(1_000)

        for surface, path, historical in (
            ("decisions", "/Home/GetExpedientes", False),
            ("historical", "/Home/GetBoletinesHistorico", True),
        ):
            for year in range(YEAR_MIN, YEAR_MAX + 1):
                response = context.request.post(
                    f"{TARGET.rstrip('/')}{path}",
                    form=form(year=year, historical=historical),
                    headers={
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": TARGET,
                    },
                    timeout=90_000,
                )
                if response.status != 200:
                    raise RuntimeError(f"{surface} {year} returned HTTP {response.status}")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError(f"{surface} {year} returned non-object JSON")
                count = int(payload.get("recordsFiltered", 0))
                rows = payload.get("data", [])
                results[surface][str(year)] = count
                if count and isinstance(rows, list) and rows:
                    row = rows[0]
                    if isinstance(row, dict):
                        samples[surface][str(year)] = {
                            "keys": sorted(row.keys()),
                            "sample": row,
                        }
                print(
                    json.dumps(
                        {
                            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "surface": surface,
                            "year": year,
                            "records_filtered": count,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        browser.close()

    summary = {
        "year_min": YEAR_MIN,
        "year_max": YEAR_MAX,
        "counts": results,
        "totals": {
            surface: sum(years.values())
            for surface, years in results.items()
        },
        "nonzero_years": {
            surface: [int(year) for year, count in years.items() if count > 0]
            for surface, years in results.items()
        },
        "samples": samples,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary["totals"], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
