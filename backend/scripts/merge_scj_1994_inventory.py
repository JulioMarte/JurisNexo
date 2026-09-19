from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

INPUT_DIR = Path(os.environ["SCJ_YEAR_INVENTORY_INPUT"])
OUTPUT_DIR = Path(os.environ["SCJ_YEAR_INVENTORY_OUTPUT"])
YEAR_MIN = int(os.environ.get("SCJ_YEAR_MIN", "1994"))
YEAR_MAX = int(os.environ.get("SCJ_YEAR_MAX", "2026"))
SURFACES = ("decisions",)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object in {path}")
    return value


def source_identifier(record: dict[str, Any]) -> tuple[str, str]:
    surface = str(record["surface"])
    row = record["row"]
    if not isinstance(row, dict):
        raise TypeError("SCJ year inventory record lacks row object")
    expediente_id = str(row.get("idExpediente") or "").strip()
    guid = str(row.get("guidBlob") or "").strip()
    if not expediente_id:
        raise ValueError("decision inventory record lacks idExpediente")
    identifier = f"expediente:{expediente_id}"
    if guid:
        identifier += f":{guid}"
    return identifier, "decisions"


def main() -> None:
    if YEAR_MIN > YEAR_MAX:
        raise ValueError("SCJ_YEAR_MIN must be <= SCJ_YEAR_MAX")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    expected_years = set(range(YEAR_MIN, YEAR_MAX + 1))

    summaries = sorted(INPUT_DIR.glob("**/*-years-shard-*-summary.json"))
    rows = sorted(INPUT_DIR.glob("**/*-years-shard-*.jsonl"))
    if not summaries or not rows:
        raise RuntimeError("year-sharded SCJ inventory artifacts are missing")

    summaries_by_surface: dict[str, list[dict[str, Any]]] = {surface: [] for surface in SURFACES}
    for path in summaries:
        summary = load_json(path)
        surface = str(summary.get("surface") or "")
        if surface not in summaries_by_surface:
            continue
        summaries_by_surface[surface].append(summary)

    coverage: dict[str, dict[str, Any]] = {}
    for surface in SURFACES:
        surface_summaries = summaries_by_surface[surface]
        if not surface_summaries:
            raise RuntimeError(f"missing {surface} year inventory summaries")
        shard_counts = {int(item["shard_count"]) for item in surface_summaries}
        if len(shard_counts) != 1:
            raise RuntimeError(f"{surface} shards disagree on shard_count")
        shard_count = shard_counts.pop()
        shard_indexes = {int(item["shard_index"]) for item in surface_summaries}
        if shard_indexes != set(range(shard_count)):
            raise RuntimeError(
                f"{surface} missing shards: expected={list(range(shard_count))} "
                f"observed={sorted(shard_indexes)}"
            )
        assigned = [
            int(year)
            for item in surface_summaries
            for year in item.get("assigned_years", [])
        ]
        assigned_counts = Counter(assigned)
        if set(assigned_counts) != expected_years:
            raise RuntimeError(
                f"{surface} year coverage mismatch: "
                f"missing={sorted(expected_years - set(assigned_counts))} "
                f"extra={sorted(set(assigned_counts) - expected_years)}"
            )
        duplicates = sorted(year for year, count in assigned_counts.items() if count != 1)
        if duplicates:
            raise RuntimeError(f"{surface} years assigned more than once: {duplicates}")

        year_reports: dict[str, Any] = {}
        for item in surface_summaries:
            for year, report in item.get("year_reports", {}).items():
                if year in year_reports:
                    raise RuntimeError(f"{surface} duplicate year report: {year}")
                year_reports[year] = report
        if {int(year) for year in year_reports} != expected_years:
            raise RuntimeError(f"{surface} summaries do not report every requested year")
        coverage[surface] = {
            "shard_count": shard_count,
            "year_reports": dict(sorted(year_reports.items(), key=lambda pair: int(pair[0]))),
        }

    unique_by_source_key: dict[tuple[str, str], dict[str, Any]] = {}
    raw_count = 0
    for path in rows:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError(f"invalid JSON object in {path}")
                surface = str(record.get("surface") or "")
                if surface not in SURFACES:
                    continue
                year = int(record.get("year"))
                if year not in expected_years:
                    raise RuntimeError(f"record outside requested year range: {year}")
                stable_key = str(record.get("_stable_key") or "")
                if not stable_key:
                    raise ValueError("SCJ year inventory record lacks stable key")
                raw_count += 1
                unique_by_source_key.setdefault((surface, stable_key), record)

    canonical_records: list[dict[str, Any]] = []
    url_sources: dict[str, list[dict[str, Any]]] = {}
    for (_, _), record in sorted(unique_by_source_key.items()):
        identifier, collection = source_identifier(record)
        document_url = str(record.get("_document_url") or "").strip()
        prepared = {
            "surface": record["surface"],
            "year": int(record["year"]),
            "source": "supreme_court",
            "source_identifier": identifier,
            "collection": collection,
            "discovery_url": "https://consultasentenciascj.poderjudicial.gob.do/",
            "document_url": document_url,
            "_stable_key": record["_stable_key"],
            "row": record["row"],
        }
        canonical_records.append(prepared)
        url_sources.setdefault(document_url, []).append(prepared)

    duplicate_urls = {
        url: [
            {
                "surface": item["surface"],
                "year": item["year"],
                "source_identifier": item["source_identifier"],
                "collection": item["collection"],
            }
            for item in items
        ]
        for url, items in url_sources.items()
        if len(items) > 1
    }

    acquisition_records: list[dict[str, Any]] = []
    for url, items in sorted(url_sources.items()):
        acquisition_records.append(dict(items[0]))

    canonical_records.sort(
        key=lambda item: (int(item["year"]), str(item["surface"]), str(item["source_identifier"]))
    )
    acquisition_records.sort(
        key=lambda item: (int(item["year"]), str(item["surface"]), str(item["source_identifier"]))
    )

    canonical_digest = hashlib.sha256()
    canonical_path = OUTPUT_DIR / "scj-1994-source.inventory.jsonl"
    with canonical_path.open("w", encoding="utf-8") as output:
        for record in canonical_records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            canonical_digest.update(line.encode("utf-8"))
            canonical_digest.update(b"\n")
            output.write(line + "\n")

    acquisition_digest = hashlib.sha256()
    acquisition_path = OUTPUT_DIR / "scj-1994-acquisition.inventory.jsonl"
    with acquisition_path.open("w", encoding="utf-8") as output:
        for record in acquisition_records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            acquisition_digest.update(line.encode("utf-8"))
            acquisition_digest.update(b"\n")
            output.write(line + "\n")

    surface_counts = Counter(str(record["surface"]) for record in canonical_records)
    year_counts = Counter(int(record["year"]) for record in canonical_records)
    acquisition_year_counts = Counter(int(record["year"]) for record in acquisition_records)
    summary = {
        "status": "COMPLETE",
        "year_min": YEAR_MIN,
        "year_max": YEAR_MAX,
        "requested_year_count": len(expected_years),
        "raw_observation_count": raw_count,
        "unique_source_record_count": len(canonical_records),
        "unique_document_url_count": len(acquisition_records),
        "duplicate_document_url_count": len(duplicate_urls),
        "surface_counts": dict(sorted(surface_counts.items())),
        "source_year_counts": {str(k): v for k, v in sorted(year_counts.items())},
        "acquisition_year_counts": {
            str(k): v for k, v in sorted(acquisition_year_counts.items())
        },
        "coverage": coverage,
        "source_inventory_sha256": canonical_digest.hexdigest(),
        "acquisition_inventory_sha256": acquisition_digest.hexdigest(),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "duplicate-document-urls.json").write_text(
        json.dumps(duplicate_urls, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
