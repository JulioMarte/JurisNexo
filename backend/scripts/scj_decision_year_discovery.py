from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from scj_year_inventory import TARGET, fetch_page

YEAR_RE = re.compile(r"^(?:19|20|21)\d{2}$")
MIN_YEAR_COUNT = int(os.environ.get("SCJ_DISCOVERY_MIN_YEAR_COUNT", "10"))


def _utc_now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _year_candidates(page: object) -> list[int]:
    selects = page.locator("select")
    candidates: list[list[int]] = []
    for index in range(selects.count()):
        values = selects.nth(index).locator("option").evaluate_all(
            """options => options.flatMap(option => [option.value, option.textContent || ""])"""
        )
        years = sorted(
            {
                int(value.strip())
                for value in values
                if isinstance(value, str)
                and YEAR_RE.fullmatch(value.strip())
            }
        )
        if years:
            candidates.append(years)
    if not candidates:
        raise RuntimeError("SCJ source surface exposes no discoverable year selector")
    return max(candidates, key=len)


def main() -> None:
    output = Path(os.environ["SCJ_YEAR_DISCOVERY_OUTPUT"])
    output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        navigation = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
        if navigation is None or navigation.status != 200:
            raise RuntimeError("SCJ portal bootstrap failed during year discovery")

        advertised_years = _year_candidates(page)
        if len(advertised_years) < MIN_YEAR_COUNT:
            raise RuntimeError(
                "SCJ discovered suspiciously few years: "
                f"{len(advertised_years)} < {MIN_YEAR_COUNT}"
            )

        year_counts: dict[str, int] = {}
        for year in advertised_years:
            count, _ = fetch_page(
                context.request,
                surface="decisions",
                year=year,
                start=0,
            )
            year_counts[str(year)] = count

        browser.close()

    active_years = [year for year in advertised_years if year_counts[str(year)] > 0]
    if not active_years:
        raise RuntimeError("SCJ year discovery found no years with decision records")

    payload = {
        "schema_version": 1,
        "source": "supreme_court",
        "surface": "decisions",
        "observed_at": _utc_now_z(),
        "advertised_years": advertised_years,
        "active_years": active_years,
        "year_counts": year_counts,
        "advertised_year_count": len(advertised_years),
        "active_year_count": len(active_years),
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
