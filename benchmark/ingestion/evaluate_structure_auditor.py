from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

_ALLOW_STATES = {"APPROVED", "APPROVED_WITH_AMENDMENTS"}
_BLOCK_STATES = {"MORE_INVESTIGATION_REQUIRED", "REJECTED", "SOURCE_QUALITY_BLOCKED"}
_ALL_STATES = _ALLOW_STATES | _BLOCK_STATES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score Structure Auditor intervention quality, false rejection, "
            "and measured token/latency overhead"
        )
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _required_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    if value < 0:
        raise ValueError(f"{key} must not be negative")
    return float(value)


def _required_case_map(payload: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{label} cases must be a non-empty list")

    cases: dict[str, dict[str, Any]] = {}
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"{label} case {index} must be an object")
        case_id = raw_case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"{label} case {index} requires case_id")
        if case_id in cases:
            raise ValueError(f"duplicate {label} case_id: {case_id}")
        cases[case_id] = raw_case
    return cases


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def score(*, result: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    result_cases = _required_case_map(result, label="result")
    gold_cases = _required_case_map(gold, label="gold")
    if set(result_cases) != set(gold_cases):
        missing = sorted(set(gold_cases) - set(result_cases))
        unexpected = sorted(set(result_cases) - set(gold_cases))
        raise ValueError(
            f"result/gold case ids differ; missing={missing}, unexpected={unexpected}"
        )

    thresholds = gold.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("gold thresholds must be an object")
    min_detection = _required_number(thresholds, "min_error_detection_recall")
    max_false_rejection = _required_number(thresholds, "max_false_rejection_rate")
    if min_detection > 1 or max_false_rejection > 1:
        raise ValueError("rate thresholds must be between 0 and 1")

    intervention_total = 0
    intervention_detected = 0
    valid_total = 0
    valid_rejected = 0
    case_reports: list[dict[str, Any]] = []
    auditor_tokens: list[float] = []
    auditor_latencies_ms: list[float] = []
    total_structure_tokens = 0.0
    total_auditor_tokens = 0.0
    total_structure_latency_ms = 0.0
    total_auditor_latency_ms = 0.0

    for case_id in sorted(gold_cases):
        expected = gold_cases[case_id]
        observed = result_cases[case_id]
        expected_action = expected.get("expected_action")
        if expected_action not in {"allow_extraction", "block_extraction"}:
            raise ValueError(f"gold case {case_id} has invalid expected_action")

        state = observed.get("audit_state")
        if state not in _ALL_STATES:
            raise ValueError(f"result case {case_id} has invalid audit_state")
        allows_extraction = state in _ALLOW_STATES
        expected_allows = expected_action == "allow_extraction"
        correct = allows_extraction == expected_allows

        structure_tokens = _required_number(observed, "structure_agent_tokens")
        case_auditor_tokens = _required_number(observed, "auditor_tokens")
        structure_latency_ms = _required_number(observed, "structure_agent_latency_ms")
        auditor_latency_ms = _required_number(observed, "auditor_latency_ms")
        total_structure_tokens += structure_tokens
        total_auditor_tokens += case_auditor_tokens
        total_structure_latency_ms += structure_latency_ms
        total_auditor_latency_ms += auditor_latency_ms
        auditor_tokens.append(case_auditor_tokens)
        auditor_latencies_ms.append(auditor_latency_ms)

        if expected_allows:
            valid_total += 1
            if not allows_extraction:
                valid_rejected += 1
        else:
            intervention_total += 1
            if not allows_extraction:
                intervention_detected += 1

        case_reports.append(
            {
                "case_id": case_id,
                "expected_action": expected_action,
                "audit_state": state,
                "allows_extraction": allows_extraction,
                "correct": correct,
                "structure_agent_tokens": structure_tokens,
                "auditor_tokens": case_auditor_tokens,
                "structure_agent_latency_ms": structure_latency_ms,
                "auditor_latency_ms": auditor_latency_ms,
            }
        )

    error_detection_recall = _ratio(intervention_detected, intervention_total)
    false_rejection_rate = 0.0 if valid_total == 0 else valid_rejected / valid_total
    token_overhead_ratio = (
        0.0 if total_structure_tokens == 0 else total_auditor_tokens / total_structure_tokens
    )
    latency_overhead_ratio = (
        0.0
        if total_structure_latency_ms == 0
        else total_auditor_latency_ms / total_structure_latency_ms
    )
    threshold_pass = (
        error_detection_recall >= min_detection
        and false_rejection_rate <= max_false_rejection
    )

    return {
        "schema_version": 1,
        "benchmark": "structure_auditor_evaluation",
        "evidence_class": "controlled_fixture_measurement",
        "status": "PASS" if threshold_pass else "FAIL",
        "metrics": {
            "intervention_case_count": intervention_total,
            "intervention_detected_count": intervention_detected,
            "error_detection_recall": error_detection_recall,
            "valid_case_count": valid_total,
            "valid_rejected_count": valid_rejected,
            "false_rejection_rate": false_rejection_rate,
            "total_structure_agent_tokens": total_structure_tokens,
            "total_auditor_tokens": total_auditor_tokens,
            "auditor_token_overhead_ratio": token_overhead_ratio,
            "median_auditor_tokens": _median(auditor_tokens),
            "total_structure_agent_latency_ms": total_structure_latency_ms,
            "total_auditor_latency_ms": total_auditor_latency_ms,
            "auditor_latency_overhead_ratio": latency_overhead_ratio,
            "median_auditor_latency_ms": _median(auditor_latencies_ms),
            "thresholds": {
                "min_error_detection_recall": min_detection,
                "max_false_rejection_rate": max_false_rejection,
            },
            "cases": case_reports,
        },
        "interpretation": (
            "This score validates the evaluation contract on controlled fixtures. "
            "It does not by itself prove live-model Structure Auditor improvement."
        ),
    }


def main() -> None:
    args = _parse_args()
    payload = score(result=_load_object(args.result), gold=_load_object(args.gold))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
