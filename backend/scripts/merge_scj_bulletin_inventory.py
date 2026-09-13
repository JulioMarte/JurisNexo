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
SURFACE = "bulletins"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object in {path}")
    return value


def main() -> None:
    """Certify every bulletin year exposed by the official SCJ selector.

    Bulletin completeness is intentionally different from decision-list completeness:
    the official source exposes a finite year selector and GetBoletines is queried for
    every exposed year. Every returned publisher row is preserved, including rows for
    which the publisher has not yet exposed a PDF.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_files = sorted(INPUT_DIR.glob("**/*-shard-*-summary.json"))
    row_files = sorted(INPUT_DIR.glob("**/*-shard-*.jsonl"))
    if not summary_files or not row_files:
        raise RuntimeError("SCJ bulletin inventory shard artifacts are missing")

    summaries: list[dict[str, Any]] = []
    for path in summary_files:
        item = load_json(path)
        if str(item.get("surface") or "") != SURFACE:
            raise ValueError(f"non-bulletin shard supplied to bulletin certifier: {path}")
        summaries.append(item)

    shard_counts = {int(item["shard_count"]) for item in summaries}
    shard_indexes = {int(item["shard_index"]) for item in summaries}
    if len(shard_counts) != 1:
        raise RuntimeError("SCJ bulletin shards disagree on shard count")
    shard_count = shard_counts.pop()
    if shard_indexes != set(range(shard_count)):
        raise RuntimeError(
            "SCJ bulletin inventory is missing shards: "
            f"expected={list(range(shard_count))}, observed={sorted(shard_indexes)}"
        )

    year_sets = {
        tuple(int(year) for year in item.get("all_years", [])) for item in summaries
    }
    if len(year_sets) != 1:
        raise RuntimeError("SCJ bulletin shards disagree on official year selector")
    official_years = set(year_sets.pop())
    if not official_years:
        raise RuntimeError("SCJ bulletin source exposed no official years")
    processed_years = {
        int(year) for item in summaries for year in item.get("processed_years", [])
    }
    if processed_years != official_years:
        raise RuntimeError(
            "SCJ bulletin enumeration did not cover every official year option: "
            f"missing={sorted(official_years - processed_years)}, "
            f"unexpected={sorted(processed_years - official_years)}"
        )

    unique: dict[str, dict[str, Any]] = {}
    captured_raw = 0
    duplicate_observations = 0
    pdf_urls: set[str] = set()
    host_counts: Counter[str] = Counter()
    metadata_only_count = 0
    normalized_url_count = 0

    for path in row_files:
        if path.name.endswith("-rejected.jsonl"):
            continue
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("row"), dict):
                    raise TypeError(f"invalid SCJ bulletin inventory record in {path}")
                if str(record.get("surface") or "") != SURFACE:
                    raise ValueError(f"unexpected SCJ surface in bulletin inventory: {path}")
                captured_raw += 1
                key = str(record.get("_stable_key") or "")
                if not key:
                    raise ValueError("SCJ bulletin record lacks stable key")
                if key in unique:
                    duplicate_observations += 1
                else:
                    unique[key] = record

                availability = str(record.get("_artifact_availability") or "available")
                document_url = record.get("_document_url")
                if availability == "available":
                    if not isinstance(document_url, str) or not document_url.startswith("https://"):
                        raise ValueError("available SCJ bulletin lacks HTTPS PDF URL")
                    pdf_urls.add(document_url)
                    host_counts[urlparse(document_url).hostname or ""] += 1
                elif availability == "not_published":
                    if document_url is not None:
                        raise ValueError("metadata-only SCJ bulletin unexpectedly has a PDF URL")
                    metadata_only_count += 1
                else:
                    raise ValueError(
                        f"unsupported SCJ bulletin artifact availability: {availability!r}"
                    )

                notes = record.get("_normalization_notes")
                if isinstance(notes, dict) and notes.get("document_url_normalization"):
                    normalized_url_count += 1

    if not unique:
        raise RuntimeError("SCJ bulletin enumeration produced no source records")

    digest = hashlib.sha256()
    output_path = OUTPUT_DIR / "scj-documents.inventory.jsonl"
    with output_path.open("w", encoding="utf-8") as output:
        for record in sorted(unique.values(), key=lambda item: str(item["_stable_key"])):
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
            output.write(line + "\n")

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "bootstrap_strategy": "bulletin_first",
        "document_bearing_surfaces": [SURFACE],
        "official_year_count": len(official_years),
        "official_year_min": min(official_years),
        "official_year_max": max(official_years),
        "official_years": sorted(official_years),
        "captured_raw_record_count": captured_raw,
        "unique_source_record_count": len(unique),
        "duplicate_transport_observation_count": duplicate_observations,
        "unique_pdf_url_count": len(pdf_urls),
        "metadata_only_record_count": metadata_only_count,
        "normalized_document_url_count": normalized_url_count,
        "pdf_host_counts": dict(sorted(host_counts.items())),
        "inventory_sha256": digest.hexdigest(),
        "enumeration_basis": (
            "Every year exposed by the official SCJ bulletin year selector was queried. "
            "All returned publisher records are preserved, including records whose PDF "
            "has not yet been published."
        ),
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
