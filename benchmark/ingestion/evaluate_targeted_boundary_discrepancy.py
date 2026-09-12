from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_SDK_PAGE_HEADER = re.compile(
    r"view_page=(?P<view>\d+)\s*\|\s*printed_page=(?P<printed>\d+)"
)
_ALLOWED_RESOLUTIONS = {
    "confirmed_at_reference",
    "confirmed_nearby",
    "unresolved",
    "contradictory",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score one targeted index/destination/boundary discrepancy investigation"
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _resolved_pages(result: dict[str, Any]) -> tuple[set[int], dict[int, int]]:
    trace = result.get("trace")
    if not isinstance(trace, list):
        raise ValueError("result trace must be a list")

    requested: set[int] = set()
    resolved: dict[int, int] = {}
    for record in trace:
        if not isinstance(record, dict):
            continue
        requested_pages = record.get("requested_printed_pages")
        if isinstance(requested_pages, list):
            requested.update(page for page in requested_pages if isinstance(page, int))

        output = record.get("output")
        if not isinstance(output, str):
            continue
        for match in _SDK_PAGE_HEADER.finditer(output):
            view_page = int(match.group("view"))
            printed_page = int(match.group("printed"))
            previous = resolved.get(printed_page)
            if previous is not None and previous != view_page:
                raise ValueError(
                    f"printed page {printed_page} resolved to multiple view pages in trace"
                )
            resolved[printed_page] = view_page
    return requested, resolved


def _typed_evidence(investigation: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw = investigation.get("evidence_pages")
    errors: list[str] = []
    if not isinstance(raw, list) or not raw:
        return [], ["evidence_pages must contain typed inspected evidence"]

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"evidence item {index} must be an object")
            continue
        view_page = item.get("view_page")
        printed_page = item.get("printed_page")
        role = item.get("role")
        if not isinstance(view_page, int) or not isinstance(printed_page, int):
            errors.append(f"evidence item {index} requires integer view_page and printed_page")
            continue
        pair = (view_page, printed_page)
        if pair in seen:
            errors.append(f"duplicate evidence mapping view={view_page} printed={printed_page}")
            continue
        seen.add(pair)
        normalized.append(
            {
                "view_page": view_page,
                "printed_page": printed_page,
                "role": role,
                "source_reference": item.get("source_reference"),
            }
        )
    return normalized, errors


def _target_investigation(result: dict[str, Any], reference: int) -> dict[str, Any] | None:
    hypothesis = result.get("hypothesis")
    if not isinstance(hypothesis, dict):
        return None
    investigations = hypothesis.get("index_reference_investigations")
    if not isinstance(investigations, list):
        return None
    matching = [
        item
        for item in investigations
        if isinstance(item, dict) and item.get("reference_as_printed") == reference
    ]
    if len(matching) != 1:
        return None
    return matching[0]


def score(
    *,
    result: dict[str, Any],
    target: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    target_id = target.get("target_id")
    if target_id != gold.get("target_id"):
        raise ValueError("target and gold target_id must match")

    reference = _required_int(target, "claimed_printed_reference")
    if reference != _required_int(gold, "claimed_printed_reference"):
        raise ValueError("target and gold claimed printed reference must match")

    expected_status = gold.get("expected_resolution_status")
    if expected_status not in _ALLOWED_RESOLUTIONS:
        raise ValueError("gold expected_resolution_status is invalid")
    expected_start = gold.get("expected_observed_start_printed_page")
    if expected_start is not None and not isinstance(expected_start, int):
        raise ValueError("gold expected observed start must be integer or null")

    neighbor_window = gold.get("investigation_window")
    if (
        not isinstance(neighbor_window, dict)
        or not isinstance(neighbor_window.get("start"), int)
        or not isinstance(neighbor_window.get("end"), int)
    ):
        raise ValueError("gold investigation_window requires integer start/end")
    window_start = neighbor_window["start"]
    window_end = neighbor_window["end"]
    if window_start > window_end:
        raise ValueError("gold investigation_window start must be <= end")

    requested, resolved = _resolved_pages(result)
    investigation = _target_investigation(result, reference)

    support_errors: list[str] = []
    evidence: list[dict[str, Any]] = []
    status: object = None
    observed_start: object = None
    explanation: object = None
    if investigation is None:
        support_errors.append("exactly one target investigation is required")
    else:
        status = investigation.get("resolution_status")
        observed_start = investigation.get("observed_decision_start_printed_page")
        explanation = investigation.get("explanation")
        evidence, evidence_errors = _typed_evidence(investigation)
        support_errors.extend(evidence_errors)

    for item in evidence:
        printed_page = item["printed_page"]
        view_page = item["view_page"]
        trace_view = resolved.get(printed_page)
        if trace_view is None:
            support_errors.append(f"printed evidence absent from trace: {printed_page}")
        elif trace_view != view_page:
            support_errors.append(
                f"trace maps printed page {printed_page} to view {trace_view}, not {view_page}"
            )

    claimed_destination_read = reference in requested and reference in resolved
    neighbor_pages = {
        page for page in requested if window_start <= page <= window_end and page != reference
    }
    neighbors_investigated = bool(neighbor_pages)
    original_reference_preserved = investigation is not None
    mismatch_recognized = status in {"confirmed_nearby", "unresolved", "contradictory"}
    explanation_present = isinstance(explanation, str) and bool(explanation.strip())
    resolution_matches_gold = status == expected_status and observed_start == expected_start
    trace_supported = not support_errors

    expected_start_evidenced = True
    if isinstance(expected_start, int):
        expected_start_evidenced = any(
            item["printed_page"] == expected_start for item in evidence
        )

    passed = all(
        (
            claimed_destination_read,
            neighbors_investigated,
            original_reference_preserved,
            mismatch_recognized,
            explanation_present,
            resolution_matches_gold,
            trace_supported,
            expected_start_evidenced,
        )
    )

    return {
        "schema_version": 1,
        "benchmark": "targeted_boundary_discrepancy",
        "target_id": target_id,
        "status": "PASS" if passed else "FAIL",
        "metrics": {
            "claimed_printed_reference": reference,
            "claimed_destination_read": claimed_destination_read,
            "neighbor_pages_investigated": sorted(neighbor_pages),
            "neighbors_investigated": neighbors_investigated,
            "original_reference_preserved": original_reference_preserved,
            "mismatch_recognized": mismatch_recognized,
            "explanation_present": explanation_present,
            "resolution_status": status,
            "observed_decision_start_printed_page": observed_start,
            "resolution_matches_gold": resolution_matches_gold,
            "trace_supported": trace_supported,
            "trace_support_errors": support_errors,
            "expected_start_evidenced": expected_start_evidenced,
            "resolved_printed_pages": sorted(resolved),
        },
    }


def main() -> None:
    args = _parse_args()
    payload = score(
        result=_load_object(args.result),
        target=_load_object(args.target),
        gold=_load_object(args.gold),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
