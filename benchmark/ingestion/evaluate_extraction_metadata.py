from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score evidence-backed extraction metadata")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _pairs(payload: dict[str, Any], *, label: str) -> set[tuple[str, str]]:
    raw = payload.get("metadata")
    if not isinstance(raw, list):
        raise ValueError(f"{label} metadata must be a list")
    pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label} metadata item {index} must be an object")
        field = item.get("field")
        value = item.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            raise ValueError(f"{label} metadata item {index} requires string field/value")
        if label == "result" and item.get("evidence_valid") is not True:
            continue
        pairs.add((field, _normalize(value)))
    return pairs


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def score(*, result: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    predicted = _pairs(result, label="result")
    expected = _pairs(gold, label="gold")
    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

    thresholds = gold.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("gold thresholds must be an object")
    min_precision = float(thresholds.get("min_precision", 1.0))
    min_recall = float(thresholds.get("min_recall", 1.0))
    passed = precision >= min_precision and recall >= min_recall

    return {
        "schema_version": 1,
        "benchmark": "extraction_metadata",
        "evidence_class": "controlled_fixture_measurement",
        "status": "PASS" if passed else "FAIL",
        "metrics": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "unsupported_or_wrong": sorted(predicted - expected),
            "missing": sorted(expected - predicted),
            "thresholds": {
                "min_precision": min_precision,
                "min_recall": min_recall,
            },
        },
        "interpretation": (
            "Controlled fixtures validate scorer behavior only; live-model metadata quality "
            "requires independently labeled extraction runs."
        ),
    }


def main() -> None:
    args = _parse_args()
    payload = score(result=_load(args.result), gold=_load(args.gold))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
