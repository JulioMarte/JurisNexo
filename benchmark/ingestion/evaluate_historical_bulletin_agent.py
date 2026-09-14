from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_RESOLVED_PAGE_PATTERNS = (
    re.compile(r"--- VIEW PAGE (?P<view>\d+) \| PRINTED PAGE (?P<printed>\d+) \| SOURCE "),
    re.compile(r"view_page=(?P<view>\d+) \| printed_page=(?P<printed>\d+)"),
)
_CONFIRMED_STATUSES = {"confirmed_at_reference", "confirmed_nearby"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score historical bulletin agent navigation against frozen index gold"
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
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
        if not isinstance(entry, dict) or not isinstance(entry.get("printed_page"), int):
            raise ValueError("every gold entry must contain an integer printed_page")
        pages.add(entry["printed_page"])
    return pages


def _resolved_pages_from_output(tool_output: str) -> dict[int, int]:
    resolved: dict[int, int] = {}
    for pattern in _RESOLVED_PAGE_PATTERNS:
        for match in pattern.finditer(tool_output):
            printed_page = int(match.group("printed"))
            view_page = int(match.group("view"))
            previous = resolved.get(printed_page)
            if previous is not None and previous != view_page:
                raise ValueError(
                    f"printed page {printed_page} resolved to multiple view pages in tool trace"
                )
            resolved[printed_page] = view_page
    return resolved


def _legacy_navigation_evidence(
    result: dict[str, Any],
) -> tuple[set[int], set[int], set[int], dict[int, int]]:
    steps = result.get("steps")
    if not isinstance(steps, list):
        return set(), set(), set(), {}
    direct: set[int] = set()
    ranges: set[int] = set()
    delegated: set[int] = set()
    resolved: dict[int, int] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        decision = step.get("decision")
        if not isinstance(decision, dict):
            continue
        tool = decision.get("tool")
        output = step.get("tool_output") if isinstance(step.get("tool_output"), str) else ""
        if tool == "get_printed_page":
            printed = decision.get("printed_page_number")
            if isinstance(printed, int):
                direct.add(printed)
        elif tool in {"get_printed_pages", "delegate_printed_pages"}:
            start = decision.get("start_printed_page_number")
            end = decision.get("end_printed_page_number")
            if isinstance(start, int) and isinstance(end, int) and start <= end:
                requested = set(range(start, end + 1))
                ranges.update(requested)
                if tool == "delegate_printed_pages":
                    delegated.update(requested)
        for printed, view in _resolved_pages_from_output(output).items():
            resolved[printed] = view
    return direct, ranges, delegated, resolved


def _iter_current_trace_events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    rounds = trace.get("rounds")
    if not isinstance(rounds, list):
        return events
    for round_payload in rounds:
        if not isinstance(round_payload, dict):
            continue
        for stage_name in ("structure_agent", "structure_auditor"):
            stage = round_payload.get(stage_name)
            if not isinstance(stage, dict):
                continue
            tool_trace = stage.get("tool_trace")
            if isinstance(tool_trace, list):
                events.extend(event for event in tool_trace if isinstance(event, dict))
    return events


def _current_navigation_evidence(
    trace: dict[str, Any],
) -> tuple[set[int], set[int], set[int], dict[int, int]]:
    direct: set[int] = set()
    ranges: set[int] = set()
    resolved: dict[int, int] = {}
    for event in _iter_current_trace_events(trace):
        tool = event.get("tool_name")
        arguments = event.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        if tool == "get_printed_page":
            printed = arguments.get("printed_page_number")
            if isinstance(printed, int):
                direct.add(printed)
        elif tool == "get_printed_pages":
            start = arguments.get("start_printed_page")
            end = arguments.get("end_printed_page")
            if isinstance(start, int) and isinstance(end, int) and start <= end:
                ranges.update(range(start, end + 1))
        excerpt = event.get("result_excerpt")
        if isinstance(excerpt, str):
            for printed, view in _resolved_pages_from_output(excerpt).items():
                previous = resolved.get(printed)
                if previous is not None and previous != view:
                    raise ValueError(
                        f"printed page {printed} changed view-page resolution during run"
                    )
                resolved[printed] = view
    return direct, ranges, set(), resolved


def _navigation_evidence(
    result: dict[str, Any], trace: dict[str, Any] | None
) -> tuple[set[int], set[int], set[int], dict[int, int]]:
    if trace is not None:
        current = _current_navigation_evidence(trace)
        if any(current):
            return current
    legacy = _legacy_navigation_evidence(result)
    if any(legacy):
        return legacy
    raise ValueError("no supported navigation trace was found")


def _typed_evidence(value: object) -> tuple[list[int], list[int]] | None:
    if not isinstance(value, list):
        return None
    printed: list[int] = []
    views: list[int] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("view_page"), int):
            return None
        views.append(item["view_page"])
        printed_page = item.get("printed_page")
        if isinstance(printed_page, int):
            printed.append(printed_page)
    return printed, views


def _int_list(value: object) -> list[int] | None:
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        return None
    return value


def _semantic_confirmations(
    result: dict[str, Any], resolved_pages: dict[int, int]
) -> tuple[set[int], set[int], list[dict[str, Any]]]:
    hypothesis = result.get("hypothesis")
    if not isinstance(hypothesis, dict):
        return set(), set(), []
    investigations = hypothesis.get("index_reference_investigations")
    if not isinstance(investigations, list):
        return set(), set(), []

    confirmed: set[int] = set()
    starts: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for investigation in investigations:
        if not isinstance(investigation, dict):
            continue
        reference = investigation.get("reference_as_printed")
        status = investigation.get("resolution_status")
        observed_start = investigation.get("observed_decision_start_printed_page")
        typed = _typed_evidence(investigation.get("evidence_pages"))
        if typed is not None:
            evidence_printed, evidence_views = typed
        else:
            evidence_printed = _int_list(investigation.get("evidence_printed_pages")) or []
            evidence_views = _int_list(investigation.get("evidence_view_pages")) or []
        if not isinstance(reference, int) or not isinstance(status, str):
            continue

        errors: list[str] = []
        if not evidence_printed or not evidence_views:
            errors.append("investigation requires source-backed printed/view evidence")
        missing = sorted(set(evidence_printed) - set(resolved_pages))
        if missing:
            errors.append("printed evidence absent from tool trace: " + ",".join(map(str, missing)))
        expected_views = {
            resolved_pages[p] for p in evidence_printed if p in resolved_pages
        }
        if set(evidence_views) != expected_views:
            errors.append("evidence view pages do not match resolved printed-page trace")
        if status in _CONFIRMED_STATUSES:
            if reference not in evidence_printed:
                errors.append("confirmed reference itself was not cited as inspected evidence")
            if not isinstance(observed_start, int) or observed_start not in evidence_printed:
                errors.append("confirmed observed start was not cited as inspected evidence")
        supported = not errors
        if status in _CONFIRMED_STATUSES and supported:
            confirmed.add(reference)
            if isinstance(observed_start, int):
                starts.add(observed_start)
        normalized.append(
            {
                "reference_as_printed": reference,
                "resolution_status": status,
                "observed_decision_start_printed_page": observed_start,
                "evidence_printed_pages": evidence_printed,
                "evidence_view_pages": evidence_views,
                "confidence": investigation.get("confidence"),
                "trace_supported": supported,
                "trace_support_errors": errors,
            }
        )
    return confirmed, starts, normalized


def main() -> None:
    args = _parse_args()
    result = _load_object(args.result)
    trace_path = args.trace
    if trace_path is None:
        sibling = args.result.with_name("structure-trace.json")
        trace_path = sibling if sibling.exists() else None
    trace = _load_object(trace_path) if trace_path is not None else None
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
    direct, ranges, delegated, resolved = _navigation_evidence(result, trace)
    attempted = direct | ranges
    verified = set(resolved)
    verified_gold = verified & gold_pages
    confirmed, starts, investigations = _semantic_confirmations(result, resolved)
    confirmed_gold = confirmed & gold_pages
    hypothesis = result.get("hypothesis")
    has_index = isinstance(hypothesis, dict) and hypothesis.get("has_index") is True

    policy = gold.get("acceptance_policy")
    if not isinstance(policy, dict):
        raise ValueError("gold acceptance_policy must be an object")
    minimum_verified = policy.get("minimum_distinct_verified_index_references")
    if not isinstance(minimum_verified, int) or minimum_verified < 1:
        raise ValueError("minimum_distinct_verified_index_references must be positive")
    require_index = policy.get("require_index_detected") is True
    navigation_passed = len(verified_gold) >= minimum_verified and (has_index or not require_index)
    semantic_available = bool(investigations)
    semantic_passed = (
        semantic_available
        and len(confirmed_gold) >= minimum_verified
        and (has_index or not require_index)
    )
    semantic_status = (
        "PASS"
        if semantic_passed
        else "FAIL"
        if semantic_available
        else "NOT_AVAILABLE"
    )

    payload = {
        "schema_version": 3,
        "dataset_id": gold.get("dataset_id"),
        "source_sha256": observed_sha256,
        "status": "PASS" if navigation_passed else "FAIL",
        "navigation_status": "PASS" if navigation_passed else "FAIL",
        "semantic_status": semantic_status,
        "metrics": {
            "gold_reference_count": len(gold_pages),
            "attempted_printed_pages": sorted(attempted),
            "direct_printed_page_attempts": sorted(direct),
            "range_printed_page_attempts": sorted(ranges),
            "delegated_printed_page_attempts": sorted(delegated),
            "investigative_neighbor_attempts": sorted(ranges - direct),
            "verified_printed_pages": sorted(verified),
            "verified_gold_references": sorted(verified_gold),
            "verified_gold_reference_count": len(verified_gold),
            "unexpected_printed_page_attempts": sorted(direct - gold_pages),
            "index_detected": has_index,
            "trace_format": "structure-trace" if trace is not None else "legacy-steps",
        },
        "semantic_metrics": {
            "confirmed_index_references": sorted(confirmed),
            "confirmed_gold_references": sorted(confirmed_gold),
            "confirmed_gold_reference_count": len(confirmed_gold),
            "observed_decision_start_printed_pages": sorted(starts),
            "investigations": investigations,
        },
        "policy": {
            "minimum_distinct_verified_index_references": minimum_verified,
            "require_index_detected": require_index,
            "note": (
                "Navigation is scored from the durable current structure trace when available; "
                "semantic confirmation requires typed evidence that is trace-backed."
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
