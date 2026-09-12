from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

INPUT_DIR = Path(os.environ["SCJ_INVENTORY_INPUT"])
OUTPUT_DIR = Path(os.environ["SCJ_INVENTORY_OUTPUT"])
SURFACES = ("decisions", "historical", "bulletins")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object in {path}")
    return value


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_files = sorted(INPUT_DIR.glob("**/*-shard-*-summary.json"))
    row_files = sorted(INPUT_DIR.glob("**/*-shard-*.jsonl"))
    if not summary_files or not row_files:
        raise RuntimeError("SCJ inventory shard artifacts are missing")

    summaries_by_surface: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in summary_files:
        item = load_json(path)
        summaries_by_surface[str(item.get("surface") or "")].append(item)

    records_by_surface: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in row_files:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("row"), dict):
                    raise TypeError(f"invalid SCJ inventory record in {path}")
                surface = str(record.get("surface") or "")
                if surface not in SURFACES:
                    raise ValueError(f"unknown SCJ inventory surface {surface!r}")
                records_by_surface[surface].append(record)

    combined_records: list[dict[str, Any]] = []
    surface_reports: dict[str, Any] = {}
    global_pdf_urls: set[str] = set()
    global_keys: set[str] = set()
    host_counts: Counter[str] = Counter()

    for surface in SURFACES:
        summaries = summaries_by_surface.get(surface, [])
        if not summaries:
            raise RuntimeError(f"SCJ inventory missing {surface} shard summaries")
        shard_counts = {int(item["shard_count"]) for item in summaries}
        shard_indexes = {int(item["shard_index"]) for item in summaries}
        if len(shard_counts) != 1:
            raise RuntimeError(f"SCJ {surface} shards disagree on shard count")
        shard_count = shard_counts.pop()
        if shard_indexes != set(range(shard_count)):
            raise RuntimeError(
                f"SCJ {surface} missing shards: expected={list(range(shard_count))}, "
                f"observed={sorted(shard_indexes)}"
            )

        records = records_by_surface.get(surface, [])
        unique: dict[str, dict[str, Any]] = {}
        duplicate_observations = 0
        pdf_urls: set[str] = set()
        for record in records:
            key = str(record.get("_stable_key") or "")
            if not key:
                raise ValueError(f"SCJ {surface} record lacks stable key")
            if key in unique:
                duplicate_observations += 1
            else:
                unique[key] = record
            row = record["row"]
            if surface == "decisions":
                url = str(row.get("urlBlob") or "").strip()
            elif surface == "historical":
                url = str(row.get("rutaDoc") or "").strip()
            else:
                url = str(row.get("urlCuerpo") or "").strip()
            if not url.startswith("https://"):
                raise ValueError(f"SCJ {surface} record lacks HTTPS PDF URL")
            pdf_urls.add(url)
            host_counts[urlparse(url).hostname or ""] += 1

        if surface in {"decisions", "historical"}:
            expected_totals = {
                int(item["expected_total_rows"])
                for item in summaries
                if item.get("expected_total_rows") is not None
            }
            if len(expected_totals) != 1:
                raise RuntimeError(
                    f"SCJ {surface} shards disagree on official recordsFiltered"
                )
            expected_total = expected_totals.pop()
            if len(unique) != expected_total:
                raise RuntimeError(
                    f"SCJ {surface} incomplete: official={expected_total}, "
                    f"unique={len(unique)}, raw={len(records)}"
                )
            enumeration_basis = (
                "SCJ live server-side DataTables endpoint; every start offset in increments of "
                "10 was requested; overlapping/oversized responses deduplicated by stable row key; "
                "unique key cardinality equals constant recordsFiltered"
            )
        else:
            year_sets = {
                tuple(int(year) for year in item.get("all_years", [])) for item in summaries
            }
            if len(year_sets) != 1:
                raise RuntimeError("SCJ bulletin shards disagree on official year selector")
            official_years = set(year_sets.pop())
            processed_years = {
                int(year)
                for item in summaries
                for year in item.get("processed_years", [])
            }
            if processed_years != official_years:
                raise RuntimeError(
                    "SCJ bulletin enumeration did not cover every official year option: "
                    f"missing={sorted(official_years - processed_years)}"
                )
            expected_total = len(unique)
            enumeration_basis = (
                "SCJ live GetBoletines endpoint queried once for every year exposed by the official "
                "year selector; all returned bulletin rows deduplicated by stable key"
            )

        for key in unique:
            if key in global_keys:
                raise RuntimeError(f"SCJ cross-surface duplicate stable key: {key}")
            global_keys.add(key)
        global_pdf_urls.update(pdf_urls)
        canonical = sorted(unique.values(), key=lambda item: str(item["_stable_key"]))
        combined_records.extend(canonical)

        surface_reports[surface] = {
            "official_record_count": expected_total,
            "captured_raw_record_count": len(records),
            "unique_stable_row_count": len(unique),
            "duplicate_observation_count": duplicate_observations,
            "unique_pdf_url_count": len(pdf_urls),
            "shard_count": shard_count,
            "enumeration_basis": enumeration_basis,
        }

    inventory_digest = hashlib.sha256()
    output_path = OUTPUT_DIR / "scj-documents.inventory.jsonl"
    with output_path.open("w", encoding="utf-8") as output:
        for record in sorted(
            combined_records,
            key=lambda item: (str(item["surface"]), str(item["_stable_key"])),
        ):
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            inventory_digest.update(line.encode("utf-8"))
            inventory_digest.update(b"\n")
            output.write(line)
            output.write("\n")

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "document_bearing_surfaces": list(SURFACES),
        "surface_reports": surface_reports,
        "unique_document_record_count": len(global_keys),
        "unique_pdf_url_count": len(global_pdf_urls),
        "pdf_host_counts": dict(sorted(host_counts.items())),
        "inventory_sha256": inventory_digest.hexdigest(),
        "excluded_non_document_surfaces": {
            "incomplete_cases": "metadata only; endpoint exposes no PDF URL",
            "incomplete_constitutional_cases": "metadata only; endpoint exposes no PDF URL",
        },
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
