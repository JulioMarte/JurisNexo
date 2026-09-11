from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = 1


def _evenly_spaced(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[0]]
    indexes = {
        round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def _load_candidates(report_paths: list[Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        source = report["source"]
        artifact_id = str(source["sha256"])
        filename = str(source["filename"])
        source_sha256 = str(source["sha256"])

        for profile in report.get("profiles", []):
            candidates.append(
                {
                    "artifact_id": artifact_id,
                    "source_filename": filename,
                    "source_sha256": source_sha256,
                    "start_page": int(profile["start_page"]),
                    "end_page": int(profile["end_page"]),
                    "layout_family": str(profile["layout"]),
                    "ordinal": int(profile["ordinal"]),
                    "parser_suggestion": {
                        "decision_numbers": list(
                            profile.get("decision_numbers_observed", [])
                        ),
                        "docket_numbers": list(profile.get("dockets_observed", [])),
                        "decision_dates": list(
                            profile.get("decision_dates_observed", [])
                        ),
                        "court_organs": list(profile.get("court_organs_observed", [])),
                        "diagnostics": list(profile.get("diagnostics", [])),
                    },
                }
            )
    return candidates


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(candidate["artifact_id"]),
        int(candidate["start_page"]),
        int(candidate["end_page"]),
    )


def _select_family(
    candidates: list[dict[str, Any]], *, limit: int, hard_fraction: float
) -> list[tuple[dict[str, Any], str]]:
    ordered = sorted(candidates, key=_candidate_key)
    hard = [item for item in ordered if item["parser_suggestion"]["diagnostics"]]
    ordinary = [item for item in ordered if not item["parser_suggestion"]["diagnostics"]]

    hard_target = min(len(hard), round(limit * hard_fraction))
    ordinary_target = min(len(ordinary), max(0, limit - hard_target))

    selected_hard = _evenly_spaced(hard, hard_target)
    selected_ordinary = _evenly_spaced(ordinary, ordinary_target)
    selected_keys = {_candidate_key(item) for item in selected_hard + selected_ordinary}

    remaining = [item for item in ordered if _candidate_key(item) not in selected_keys]
    fill_count = max(0, limit - len(selected_keys))
    selected_fill = _evenly_spaced(remaining, fill_count)

    result: list[tuple[dict[str, Any], str]] = []
    result.extend((item, "diagnostic_hard_case") for item in selected_hard)
    result.extend((item, "ordinary_stratum") for item in selected_ordinary)
    result.extend((item, "stratum_fill") for item in selected_fill)
    return sorted(result, key=lambda value: _candidate_key(value[0]))


def build_packet(
    report_paths: list[Path],
    *,
    per_family: int,
    hard_fraction: float,
) -> list[dict[str, Any]]:
    if per_family <= 0:
        raise ValueError("per_family must be positive")
    if not 0.0 <= hard_fraction <= 1.0:
        raise ValueError("hard_fraction must be between 0 and 1")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in _load_candidates(report_paths):
        by_family[str(candidate["layout_family"])].append(candidate)

    packet: list[dict[str, Any]] = []
    for family in sorted(by_family):
        for candidate, reason in _select_family(
            by_family[family], limit=per_family, hard_fraction=hard_fraction
        ):
            packet.append(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "review_status": "pending",
                    "artifact_id": candidate["artifact_id"],
                    "source_filename": candidate["source_filename"],
                    "source_sha256": candidate["source_sha256"],
                    "start_page": candidate["start_page"],
                    "end_page": candidate["end_page"],
                    "layout_family": candidate["layout_family"],
                    "sample_reason": reason,
                    "annotated_fields": [],
                    "decision_number": None,
                    "docket_numbers": [],
                    "decision_date": None,
                    "court_organ": None,
                    "parser_suggestion": candidate["parser_suggestion"],
                    "review_notes": None,
                }
            )
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic pending SCJ parser annotation packet."
    )
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-family", type=int, default=12)
    parser.add_argument("--hard-fraction", type=float, default=0.35)
    args = parser.parse_args()

    packet = build_packet(
        args.reports,
        per_family=args.per_family,
        hard_fraction=args.hard_fraction,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in packet:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts: dict[str, int] = defaultdict(int)
    for row in packet:
        counts[str(row["layout_family"])] += 1
    print(
        json.dumps(
            {
                "review_status": "pending",
                "rows": len(packet),
                "by_family": dict(sorted(counts.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
