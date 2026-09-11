from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = 1


def _load_profiles(input_dir: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    profile_paths = sorted(input_dir.rglob("*-profile.json"))
    if not profile_paths:
        raise ValueError(f"no *-profile.json files found under {input_dir}")

    for profile_path in profile_paths:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        source = payload["source"]
        filename = str(source["filename"])
        sha256 = str(source["sha256"])
        artifact_id = f"sha256:{sha256}"

        for profile in payload.get("profiles", []):
            diagnostics = tuple(sorted(set(profile.get("diagnostics", ()))))
            candidates.append(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "review_status": "pending",
                    "artifact_id": artifact_id,
                    "source_filename": filename,
                    "source_sha256": sha256,
                    "ordinal": int(profile["ordinal"]),
                    "start_page": int(profile["start_page"]),
                    "end_page": int(profile["end_page"]),
                    "layout_family": str(profile["layout"]),
                    "parser_decision_numbers": list(
                        profile.get("decision_numbers_observed", ())
                    ),
                    "parser_docket_numbers": list(profile.get("dockets_observed", ())),
                    "parser_decision_dates": list(
                        profile.get("decision_dates_observed", ())
                    ),
                    "parser_court_organs": list(
                        profile.get("court_organs_observed", ())
                    ),
                    "parser_diagnostics": list(diagnostics),
                    "annotated_fields": [],
                    "decision_number": None,
                    "docket_numbers": [],
                    "decision_date": None,
                    "court_organ": None,
                    "review_notes": None,
                }
            )

    boundary_keys = {
        (row["artifact_id"], row["start_page"], row["end_page"]) for row in candidates
    }
    if len(boundary_keys) != len(candidates):
        raise ValueError("duplicate candidate boundary key across profiler inputs")
    return candidates


def _candidate_sort_key(row: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(row["source_filename"]),
        int(row["start_page"]),
        int(row["end_page"]),
    )


def _diagnostic_priority(row: dict[str, Any]) -> tuple[int, int, tuple[str, int, int]]:
    diagnostics = row["parser_diagnostics"]
    return (
        0 if diagnostics else 1,
        -len(diagnostics),
        _candidate_sort_key(row),
    )


def _round_robin_stratified(
    candidates: list[dict[str, Any]], target: int
) -> list[dict[str, Any]]:
    if target <= 0:
        return []
    if len(candidates) <= target:
        return sorted(candidates, key=_candidate_sort_key)

    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, int, int]] = set()

    diagnostics_first = sorted(candidates, key=_diagnostic_priority)
    for row in diagnostics_first:
        if not row["parser_diagnostics"]:
            break
        if len(selected) >= target:
            break
        key = (row["artifact_id"], row["start_page"], row["end_page"])
        selected.append(row)
        selected_keys.add(key)

    remaining = [
        row
        for row in candidates
        if (row["artifact_id"], row["start_page"], row["end_page"])
        not in selected_keys
    ]

    groups: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(remaining, key=_candidate_sort_key):
        groups[(row["layout_family"], row["source_filename"])].append(row)

    group_keys = sorted(groups)
    while len(selected) < target and group_keys:
        next_group_keys: list[tuple[str, str]] = []
        for group_key in group_keys:
            group = groups[group_key]
            if group and len(selected) < target:
                selected.append(group.popleft())
            if group:
                next_group_keys.append(group_key)
        group_keys = next_group_keys

    return sorted(selected, key=_candidate_sort_key)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic, stratified SCJ review queue from parser profiles. "
            "The output is pending review and is never gold automatically."
        )
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", type=int, default=80)
    args = parser.parse_args()

    candidates = _load_profiles(args.input_dir)
    selected = _round_robin_stratified(candidates, args.target)
    _write_jsonl(args.output, selected)

    all_by_family = Counter(str(row["layout_family"]) for row in candidates)
    selected_by_family = Counter(str(row["layout_family"]) for row in selected)
    selected_by_source = Counter(str(row["source_filename"]) for row in selected)
    selected_with_diagnostics = sum(bool(row["parser_diagnostics"]) for row in selected)

    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "classification": "review_queue_not_gold",
        "selection_method": (
            "all parser-diagnostic cases first, then deterministic round-robin "
            "stratification by layout family and source compilation"
        ),
        "candidate_cases": len(candidates),
        "target_cases": args.target,
        "selected_cases": len(selected),
        "selected_with_parser_diagnostics": selected_with_diagnostics,
        "all_cases_by_family": dict(sorted(all_by_family.items())),
        "selected_cases_by_family": dict(sorted(selected_by_family.items())),
        "selected_cases_by_source": dict(sorted(selected_by_source.items())),
        "review_contract": {
            "review_status_initial": "pending",
            "allowed_final_statuses": ["reviewed", "adjudicated"],
            "parser_predictions_are_hints_only": True,
            "reviewer_must_verify_primary_source_pages": True,
            "gold_evaluator_accepts_only_reviewed_or_adjudicated_rows": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
