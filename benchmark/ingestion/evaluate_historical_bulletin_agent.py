from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_PRINTED_PAGE_MARKER = re.compile(r"PRINTED PAGE (\d+)")
_CONFIRMED_STATUSES = {"confirmed_at_reference", "confirmed_nearby"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score historical bulletin agent navigation against frozen index gold"
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--sha256", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _source_sha256(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip().split()[0]
    if len(value) != 64:
        raise ValueError("sha256 evidence must start with a 64-character digest")
    return value


def _gold_pages(gold: dict[str, Any]) -> set[int]:
    entries = gold.get("entries")
    if not isinstance(entries, list):
        raise ValueError("gold entries must be a list")

    pages: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("every gold entry must be an object")
        printed_page = entry.get("printed_page")
        if not isinstance(printed_page, int):
            raise ValueError("every gold entry must contain an integer printed_page")
        pages.add(printed_page)
    return pages


def _verified_navigation_pages(result: dict[str, Any]) -> tuple[set[int], set[int]]:
    steps = result.get("steps")
    if not isinstance(steps, list):
        raise ValueError("discovery result steps must be a list")

    attempted: set[int] = set()
    verified: set[int] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        decision = step.get("decision")
        if not isinstance(decision, dict):
            continue
        tool = decision.get("tool")
        tool_output = step.get("tool_output")
        if not isinstance(tool_output, str):
            tool_output = ""

        if tool == "get_printed_page":
            printed_page = decision.get("printed_page_number")
            if not isinstance(printed_page, int):
                continue
            attempted.add(printed_page)
            if (
                f"PRINTED PAGE {printed_page}" in tool_output
                and "SOURCE physical_pages=" in tool_output
            ):
                verified.add(printed_page)
            continue

        if tool != "get_printed_pages":
            continue
        start = decision.get("start_printed_page_number")
        end = decision.get("end_printed_page_number")
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            continue
        attempted.update(range(start, end + 1))
        for match in _PRINTED_PAGE_MARKER.finditer(tool_output):
            printed_page = int(match.group(1))
            if start <= printed_page <= end and "SOURCE physical_pages=" in tool_output:
                verified.add(printed_page)

    return attempted, verified


def _semantic_confirmations(result: dict[str, Any]) -> tuple[set[int], set[int], list[dict[str, Any]]]:
    hypothesis = result.get("hypothesis")
    if not isinstance(hypothesis, dict):
        return set(), set(), []
    investigations = hypothesis.get("index_reference_investigations")
    if not isinstance(investigations, list):
        return set(), set(), []

    confirmed_references: set[int] = set()
    observed_starts: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for investigation in investigations:
        if not isinstance(investigation, dict):
            continue
        reference = investigation.get("reference_as_printed")
        status = investigation.get("resolution_status")
        observed_start = investigation.get("observed_decision_start_printed_page")
        if not isinstance(reference, int) or not isinstance(status, str):
            continue
        if status in _CONFIRMED_STATUSES:
            confirmed_references.add(reference)
            if isinstance(observed_start, int):
                observed_starts.add(observed_start)
        normalized.append(
            {
                "reference_as_printed": reference,
                "resolution_status": status,
                "observed_decision_start_printed_page": observed_start,
                "evidence_printed_pages": investigation.get("evidence_printed_pages", []),
                "confidence": investigation.get("confidence"),
            }
        )
    return confirmed_references, observed_starts, normalized


def main() -> None:
    args = _parse_args()
    result = _load_object(args.result)
    gold = _load_object(args.gold)
    observed_sha256 = _source_sha256(args.sha256)

    expected_sha256 = gold.get("source_sha256")
    if not isinstance(expected_sha256, str):
        raise ValueError("gold source_sha256 must be a string")
    if observed_sha256 != expected_sha256:
        raise SystemExit(
            "source SHA-256 does not match frozen historical bulletin gold; refusing to score"
        )

    gold_pages = _gold_pages(gold)
    attempted_pages, verified_pages = _verified_navigation_pages(result)
    verified_gold_pages = verified_pages & gold_pages
    unexpected_attempts = attempted_pages - gold_pages
    confirmed_references, observed_starts, investigations = _semantic_confirmations(result)
    confirmed_gold_references = confirmed_references & gold_pages

    hypothesis = result.get("hypothesis")
    has_index = isinstance(hypothesis, dict) and hypothesis.get("has_index") is True

    policy = gold.get("acceptance_policy")
    if not isinstance(policy, dict):
        raise ValueError("gold acceptance_policy must be an object")
    minimum_verified = policy.get("minimum_distinct_verified_index_references")
    if not isinstance(minimum_verified, int) or minimum_verified < 1:
        raise ValueError("minimum_distinct_verified_index_references must be positive")
    require_index_detected = policy.get("require_index_detected") is True

    navigation_passed = len(verified_gold_pages) >= minimum_verified and (
        has_index or not require_index_detected
    )
    semantic_available = bool(investigations)
    semantic_passed = semantic_available and len(confirmed_gold_references) >= minimum_verified and (
        has_index or not require_index_detected
    )

    payload = {
        "schema_version": 2,
        "dataset_id": gold.get("dataset_id"),
        "source_sha256": observed_sha256,
        "status": "PASS" if navigation_passed else "FAIL",
        "navigation_status": "PASS" if navigation_passed else "FAIL",
        "semantic_status": (
            "PASS" if semantic_passed else "FAIL" if semantic_available else "NOT_AVAILABLE"
        ),
        "metrics": {
            "gold_reference_count": len(gold_pages),
            "attempted_printed_pages": sorted(attempted_pages),
            "verified_printed_pages": sorted(verified_pages),
            "verified_gold_references": sorted(verified_gold_pages),
            "verified_gold_reference_count": len(verified_gold_pages),
            "unexpected_printed_page_attempts": sorted(unexpected_attempts),
            "index_detected": has_index,
        },
        "semantic_metrics": {
            "confirmed_index_references": sorted(confirmed_references),
            "confirmed_gold_references": sorted(confirmed_gold_references),
            "confirmed_gold_reference_count": len(confirmed_gold_references),
            "observed_decision_start_printed_pages": sorted(observed_starts),
            "investigations": investigations,
        },
        "policy": {
            "minimum_distinct_verified_index_references": minimum_verified,
            "require_index_detected": require_index_detected,
            "note": (
                "status preserves the frozen v1 navigation acceptance rule; semantic_status "
                "separately measures model-supported reference confirmation without rewriting gold"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
