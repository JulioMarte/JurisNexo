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


def certify_position_coverage(
    *, surface: str, records: list[dict[str, Any]], expected_total: int
) -> tuple[dict[str, list[int]], int, int]:
    """Certify every official DataTables row position exactly maps to one stable source key.

    The live SCJ endpoint is allowed to return oversized/overlapping pages and the official
    result set itself can contain repeated logical documents. Therefore recordsFiltered is
    a count of source row positions, not a count of unique document identities.
    """
    if expected_total <= 0:
        raise RuntimeError(f"SCJ {surface} reported a non-positive official row count")

    key_positions: dict[str, set[int]] = defaultdict(set)
    position_keys: dict[int, set[str]] = defaultdict(set)
    observed_position_count: Counter[int] = Counter()

    for record in records:
        row = record.get("row")
        if not isinstance(row, dict):
            raise TypeError(f"SCJ {surface} inventory record lacks row object")
        raw_position = row.get("linea")
        if not isinstance(raw_position, int):
            raise ValueError(f"SCJ {surface} source row lacks integer linea")
        if not 1 <= raw_position <= expected_total:
            raise ValueError(
                f"SCJ {surface} source row linea outside official range: "
                f"linea={raw_position}, official={expected_total}"
            )
        key = str(record.get("_stable_key") or "")
        if not key:
            raise ValueError(f"SCJ {surface} record lacks stable key")
        key_positions[key].add(raw_position)
        position_keys[raw_position].add(key)
        observed_position_count[raw_position] += 1

    ambiguous_positions = {
        position: sorted(keys)
        for position, keys in position_keys.items()
        if len(keys) != 1
    }
    if ambiguous_positions:
        sample = dict(list(sorted(ambiguous_positions.items()))[:10])
        raise RuntimeError(
            f"SCJ {surface} source positions map to conflicting stable keys: {sample}"
        )

    expected_positions = set(range(1, expected_total + 1))
    observed_positions = set(position_keys)
    missing_positions = sorted(expected_positions - observed_positions)
    if missing_positions:
        raise RuntimeError(
            f"SCJ {surface} incomplete source-row coverage: official={expected_total}, "
            f"observed_positions={len(observed_positions)}, missing_count={len(missing_positions)}, "
            f"missing_sample={missing_positions[:20]}"
        )

    duplicate_transport_observations = sum(
        count - 1 for count in observed_position_count.values() if count > 1
    )
    repeated_source_positions = sum(len(positions) - 1 for positions in key_positions.values())
    normalized_positions = {key: sorted(positions) for key, positions in key_positions.items()}
    return normalized_positions, duplicate_transport_observations, repeated_source_positions


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
        if path.name.endswith("-rejected.jsonl"):
            continue
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
    metadata_only_count = 0
    normalized_url_count = 0

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
        duplicate_stable_key_observations = 0
        pdf_urls: set[str] = set()
        surface_metadata_only = 0
        surface_normalized = 0
        for record in records:
            key = str(record.get("_stable_key") or "")
            if not key:
                raise ValueError(f"SCJ {surface} record lacks stable key")
            if key in unique:
                duplicate_stable_key_observations += 1
            else:
                unique[key] = record
            availability = str(record.get("_artifact_availability") or "available")
            document_url = record.get("_document_url")
            if availability == "available":
                if not isinstance(document_url, str) or not document_url.startswith("https://"):
                    raise ValueError(f"SCJ {surface} available record lacks HTTPS PDF URL")
                pdf_urls.add(document_url)
                host_counts[urlparse(document_url).hostname or ""] += 1
            elif availability == "not_published":
                if document_url is not None:
                    raise ValueError(
                        f"SCJ {surface} metadata-only record unexpectedly has document URL"
                    )
                surface_metadata_only += 1
            else:
                raise ValueError(
                    f"SCJ {surface} unsupported artifact availability: {availability!r}"
                )
            notes = record.get("_normalization_notes")
            if isinstance(notes, dict) and notes.get("document_url_normalization"):
                surface_normalized += 1

        source_position_count: int | None = None
        repeated_source_position_count = 0
        duplicate_transport_observation_count = 0
        source_positions_by_key: dict[str, list[int]] = {}

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
            (
                source_positions_by_key,
                duplicate_transport_observation_count,
                repeated_source_position_count,
            ) = certify_position_coverage(
                surface=surface,
                records=records,
                expected_total=expected_total,
            )
            source_position_count = expected_total
            enumeration_basis = (
                "SCJ live server-side DataTables endpoint; every start offset in increments of 10 "
                "was requested. Completeness is certified against the endpoint's official linea "
                "positions 1..recordsFiltered because the transport can return overlapping/oversized "
                "pages and the official listing itself can repeat the same logical document on multiple "
                "linea positions. Logical documents are deduplicated only after complete source-row "
                "coverage is proven."
            )
        else:
            year_sets = {
                tuple(int(year) for year in item.get("all_years", [])) for item in summaries
            }
            if len(year_sets) != 1:
                raise RuntimeError("SCJ bulletin shards disagree on official year selector")
            official_years = set(year_sets.pop())
            processed_years = {
                int(year) for item in summaries for year in item.get("processed_years", [])
            }
            if processed_years != official_years:
                raise RuntimeError(
                    "SCJ bulletin enumeration did not cover every official year option: "
                    f"missing={sorted(official_years - processed_years)}"
                )
            expected_total = len(unique)
            enumeration_basis = (
                "SCJ live GetBoletines endpoint queried once for every year exposed by the official "
                "year selector; all returned source records are preserved even when the source has "
                "not published a PDF"
            )

        canonical: list[dict[str, Any]] = []
        for key, record in unique.items():
            if key in global_keys:
                raise RuntimeError(f"SCJ cross-surface duplicate stable key: {key}")
            global_keys.add(key)
            prepared = dict(record)
            if source_positions_by_key:
                positions = source_positions_by_key[key]
                prepared["_source_positions"] = positions
                notes_value = prepared.get("_normalization_notes")
                notes = dict(notes_value) if isinstance(notes_value, dict) else {}
                if len(positions) > 1:
                    notes["repeated_official_source_positions"] = positions
                prepared["_normalization_notes"] = notes
            canonical.append(prepared)

        global_pdf_urls.update(pdf_urls)
        canonical.sort(key=lambda item: str(item["_stable_key"]))
        combined_records.extend(canonical)
        metadata_only_count += surface_metadata_only
        normalized_url_count += surface_normalized

        surface_reports[surface] = {
            "official_record_count": expected_total,
            "official_source_position_count": source_position_count,
            "captured_raw_record_count": len(records),
            "unique_stable_row_count": len(unique),
            "duplicate_stable_key_observation_count": duplicate_stable_key_observations,
            "duplicate_transport_observation_count": duplicate_transport_observation_count,
            "repeated_official_source_position_count": repeated_source_position_count,
            "unique_pdf_url_count": len(pdf_urls),
            "metadata_only_record_count": surface_metadata_only,
            "normalized_document_url_count": surface_normalized,
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
            output.write(line + "\n")

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "document_bearing_surfaces": list(SURFACES),
        "surface_reports": surface_reports,
        "unique_source_record_count": len(global_keys),
        "unique_pdf_url_count": len(global_pdf_urls),
        "metadata_only_record_count": metadata_only_count,
        "normalized_document_url_count": normalized_url_count,
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
