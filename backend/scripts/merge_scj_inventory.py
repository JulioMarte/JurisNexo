from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

INPUT_DIR = Path(os.environ["SCJ_INVENTORY_INPUT"])
OUTPUT_DIR = Path(os.environ["SCJ_INVENTORY_OUTPUT"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_files = sorted(INPUT_DIR.glob("**/shard-*-summary.json"))
    row_files = sorted(INPUT_DIR.glob("**/shard-*.jsonl"))
    if not summary_files or not row_files:
        raise RuntimeError("SCJ inventory shard artifacts are missing")

    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in summary_files]
    expected_totals = {int(item["expected_total_rows"]) for item in summaries}
    shard_counts = {int(item["shard_count"]) for item in summaries}
    shard_indexes = {int(item["shard_index"]) for item in summaries}
    if len(expected_totals) != 1:
        raise RuntimeError(f"SCJ shards disagree on total inventory size: {sorted(expected_totals)}")
    if len(shard_counts) != 1:
        raise RuntimeError("SCJ shards disagree on shard count")
    shard_count = shard_counts.pop()
    if shard_indexes != set(range(shard_count)):
        raise RuntimeError(
            f"SCJ inventory is missing shards: expected={list(range(shard_count))}, "
            f"observed={sorted(shard_indexes)}"
        )
    expected_total = expected_totals.pop()

    records: list[dict[str, Any]] = []
    stable_keys: set[str] = set()
    pdf_urls: set[str] = set()
    duplicate_keys: list[str] = []
    host_counts: Counter[str] = Counter()
    for path in row_files:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("row"), dict):
                    raise TypeError(f"invalid SCJ inventory record in {path}")
                key = str(record.get("_stable_key") or "")
                if not key:
                    raise ValueError("SCJ inventory record lacks stable key")
                if key in stable_keys:
                    duplicate_keys.append(key)
                stable_keys.add(key)
                row = record["row"]
                url = str(row.get("urlBlob") or "").strip()
                if not url.startswith("https://"):
                    raise ValueError("SCJ decision inventory contains a row without HTTPS urlBlob")
                pdf_urls.add(url)
                host_counts[urlparse(url).hostname or ""] += 1
                records.append(record)

    records.sort(
        key=lambda item: (
            int(item["_page_index"]),
            int(item["_offset"]),
        )
    )
    if len(records) != expected_total:
        raise RuntimeError(
            f"SCJ inventory incomplete: expected {expected_total} rows, captured {len(records)}"
        )
    if duplicate_keys:
        raise RuntimeError(
            f"SCJ inventory paging produced {len(duplicate_keys)} duplicate stable rows"
        )
    if len(stable_keys) != expected_total:
        raise RuntimeError("SCJ stable-key cardinality does not match official row count")

    inventory_digest = hashlib.sha256()
    output_path = OUTPUT_DIR / "scj-decisions.inventory.jsonl"
    with output_path.open("w", encoding="utf-8") as output:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            inventory_digest.update(line.encode("utf-8"))
            inventory_digest.update(b"\n")
            output.write(line)
            output.write("\n")

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "document_type": "Decisiones",
        "official_record_count": expected_total,
        "captured_record_count": len(records),
        "unique_stable_row_count": len(stable_keys),
        "unique_pdf_url_count": len(pdf_urls),
        "duplicate_stable_row_count": len(duplicate_keys),
        "pdf_host_counts": dict(sorted(host_counts.items())),
        "inventory_sha256": inventory_digest.hexdigest(),
        "shard_count": shard_count,
        "page_size": int(summaries[0]["page_size"]),
        "enumeration_basis": (
            "SCJ live GetExpedientes DataTables endpoint; every server-side page captured, "
            "constant recordsFiltered required across all shards"
        ),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
