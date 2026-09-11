from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_RESOLVED_PAGE_HEADER = re.compile(
    r"--- VIEW PAGE (?P<view>\d+) \| PRINTED PAGE (?P<printed>\d+) \| SOURCE "
)
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


def _resolved_pages_from_output(tool_output: str) -> dict[int, int]:
    resolved: dict[int, int] = {}
    for match in _RESOLVED_PAGE_HEADER.finditer(tool_output):
        printed_page = int(match.group("printed"))
        view_page = int(match.group("view"))
        previous = resolved.get(printed_page)
        if previous is not None and previous != view_page:
            raise ValueError(
                f"printed page {printed_page} resolved to multiple view pages in tool trace"
            )
        resolved[printed_page] = view_page
    return resolved


def _navigation_evidence(
    result: dict[str, Any],
) -> tuple[set[int], set[int], set[int], dict[int, int]]:
    steps = result.get("steps")
    if not isinstance(steps, list):
        raise ValueError("discovery result steps must be a list")

    direct_attempts: set[int] = set()
    range_attempts: set[int] = set()
    delegated_range_attempts: set[int] = set()
    resolved: dict[int, int] = {}
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
            direct_attempts.add(printed_page)
        elif tool in {"get_printed_pages", "delegate_printed_pages"}:
            start = decision.get("start_printed_page_number")
            end = decision.get("end_printed_page_number")
            if not isinstance(start, int) or not isinstance(end, int) or start > end:
                continue
            requested = set(range(start, end + 1))
            range_attempts.update(requested)
            if tool == "delegate_printed_pages":
                delegated_range_attempts.update(requested)
        else:
            continue

        # For delegated reads this intentionally scores only page headers that the
        # harness exposed back to the parent as trace-backed evidence. The whole
        # delegated range is not silently treated as parent-visible evidence.
        for printed_page, view_page in _resolved_pages_from_output(tool_output).items():
            previous = resolved.get(printed_page)
            if previous is not None and previous != view_page:
                raise ValueError(
                    f"printed page {printed_page} changed view-page resolution during run"
                )
            resolved[printed_page] = view_page

    return direct_attempts, range_attempts, delegated_range_attempts, resolved


def _int_list(value: object) -> list[int] | None:
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        return None
    return value


def _semantic_confirmations(
    result: dict[str, Any],
    resolved_pages: dict[int, int],
) -> tuple[set[int], set[int], list[dict[str, Any]]]:
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
        evidence_printed = _int_list(investigation.get("evidence_printed_pages"))
        evidence_views = _int_list(investigation.get("evidence_view_pages"))
        if not isinstance(reference, int) or not isinstance(status, str):
            continue

        support_errors: list[str] = []
        if evidence_printed is None or not evidence_printed:
            support_errors.append(
                "evidence_printed_pages must contain inspected printed pages"
            )
            evidence_printed = []
        if evidence_views is None or not evidence_views:
            support_errors.append(
                "evidence_view_pages must contain inspected view pages"
            )
            evidence_views = []

        missing_from_trace = sorted(set(evidence_printed) - set(resolved_pages))
        if missing_from_trace:
            support_errors.append(
                "printed evidence absent from tool trace: "
                + ",".join(str(value) for value in missing_from_trace)
            )

        expected_views = {
            resolved_pages[printed_page]
            for printed_page in evidence_printed
            if printed_page in resolved_pages
        }
        if set(evidence_views) != expected_views:
            support_errors.append(
                "evidence_view_pages do not match resolved printed-page trace"
            )

        if status in _CONFIRMED_STATUSES:
            if reference not in evidence_printed:
                support_errors.append(
                    "confirmed reference itself was not cited as inspected evidence"
                )
            if (
                not isinstance(observed_start, int)
                or observed_start not in evidence_printed
            ):
                support_errors.append(
                    "confirmed observed start was not cited as inspected evidence"
                )

        trace_supported = not support_errors
        if status in _CONFIRMED_STATUSES and trace_supported:
            confirmed_references.add(reference)
            if isinstance(observed_start, int):
                observed_starts.add(observed_start)

        normalized.append(
            {
                "reference_as_printed": reference,
                "resolution_status": status,
                "observed_decision_start_printed_page": observed_start,
                "evidence_printed_pages": evidence_printed,
                "evidence_view_pages": evidence_views,
                "confidence": investigation.get("confidence"),
                "trace_supported": trace_supported,
                "trace_support_errors": support_errors,
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
    (
        direct_attempts,
        range_attempts,
        delegated_range_attempts,
        resolved_pages,
    ) = _navigation_evidence(result)
    attempted_pages = direct_attempts | range_attempts
    investigative_neighbors = range_attempts - direct_attempts
    verified_pages = set(resolved_pages)
    verified_gold_pages = verified_pages & gold_pages
    unexpected_direct_attempts = direct_attempts - gold_pages
    confirmed_references, observed_starts, investigations = _semantic_confirmations(
        result,
        resolved_pages,
    )
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
    enough_semantic_confirmations = len(confirmed_gold_references) >= minimum_verified
    semantic_passed = semantic_available and enough_semantic_confirmations and (
        has_index or not require_index_detected
    )

    payload = {
        "schema_version": 2,
        "dataset_id": gold.get("dataset_id"),
        "source_sha256": observed_sha256,
        "status": "PASS" if navigation_passed else "FAIL",
        "navigation_status": "PASS" if navigation_passed else "FAIL",
        "semantic_status": (
            "PASS"
            if semantic_passed
            else "FAIL"
            if semantic_available
            else "NOT_AVAILABLE"
        ),
        "metrics": {
            "gold_reference_count": len(gold_pages),
            "attempted_printed_pages": sorted(attempted_pages),
            "direct_printed_page_attempts": sorted(direct_attempts),
            "range_printed_page_attempts": sorted(range_attempts),
            "delegated_printed_page_attempts": sorted(delegated_range_attempts),
            "investigative_neighbor_attempts": sorted(investigative_neighbors),
            "verified_printed_pages": sorted(verified_pages),
            "verified_gold_references": sorted(verified_gold_pages),
            "verified_gold_reference_count": len(verified_gold_pages),
            "unexpected_printed_page_attempts": sorted(unexpected_direct_attempts),
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
                "status preserves the frozen v1 navigation acceptance rule; "
                "semantic_status requires evidence exposed in the parent tool trace, "
                "including trace-backed evidence returned by delegated locators"
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
