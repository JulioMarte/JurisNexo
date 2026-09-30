from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from jurisnexo.normalization.gold import score_text_fidelity  # noqa: E402


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("prepared manifest has no cases")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        sample_id = str(case["sample_id"])
        if sample_id in result:
            raise RuntimeError(f"duplicate sample_id in manifest: {sample_id}")
        if case.get("reference_reliable") is not True:
            raise RuntimeError(f"unreliable reference in manifest: {sample_id}")
        result[sample_id] = case
    return result


def _load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        sample_id = str(row["sample_id"])
        if sample_id in result:
            raise RuntimeError(f"duplicate prediction: {sample_id}")
        result[sample_id] = row
    return result


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _critical_counts(score: Any) -> tuple[int, int]:
    expected = sum(item.expected for item in score.critical.values())
    matched = sum(item.matched for item in score.critical.values())
    return expected, matched


def score_engine(
    manifest_path: Path,
    predictions_path: Path,
    runtime_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    cases = _load_manifest(manifest_path)
    predictions = _load_predictions(predictions_path)
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    observed = set(predictions)
    expected = set(cases)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise RuntimeError(
            f"prediction identity mismatch: missing={missing[:5]} "
            f"unexpected={unexpected[:5]}"
        )

    rows: list[dict[str, Any]] = []
    failure_reasons: Counter[str] = Counter()
    total_critical_expected = 0
    total_critical_matched = 0

    for sample_id in sorted(cases):
        case = cases[sample_id]
        prediction = predictions[sample_id]
        error = prediction.get("error")
        candidate = str(prediction.get("text") or "")
        reference_path = manifest_path.parent / str(case["reference_path"])
        reference = reference_path.read_text(encoding="utf-8")
        row: dict[str, Any] = {
            "sample_id": sample_id,
            "object_key": str(case["object_key"]),
            "page_index": int(case["page_index"]),
            "elapsed_ms": int(prediction.get("elapsed_ms") or 0),
            "error": error,
        }
        if error:
            failure_reasons[str(error).split(":", 1)[0]] += 1
            row["metrics"] = None
        else:
            score = score_text_fidelity(
                expected_text=reference,
                candidate_text=candidate,
            )
            critical_expected, critical_matched = _critical_counts(score)
            total_critical_expected += critical_expected
            total_critical_matched += critical_matched
            row["metrics"] = {
                "character_error_rate": score.character_error_rate,
                "word_error_rate": score.word_error_rate,
                "token_content_recall": score.token_content_recall,
                "token_content_precision": score.token_content_precision,
                "token_content_f1": score.token_content_f1,
                "token_order_preservation": score.token_order_preservation,
                "legal_critical_recall": score.legal_critical_recall,
                "critical_expected": critical_expected,
                "critical_matched": critical_matched,
                "missing_span_count": score.missing_span_count,
            }
        rows.append(row)

    successful = [row for row in rows if row["metrics"] is not None]
    metrics = [row["metrics"] for row in successful]
    failure_rate = 1.0 - (len(successful) / len(rows))
    aggregate_critical_recall = (
        None
        if not successful
        else (
            1.0
            if total_critical_expected == 0
            else total_critical_matched / total_critical_expected
        )
    )
    summary = {
        "schema_version": 1,
        "engine": runtime["engine"],
        "engine_version": runtime.get("engine_version"),
        "page_count": len(rows),
        "successful_pages": len(successful),
        "failed_pages": len(rows) - len(successful),
        "failure_rate": failure_rate,
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "mean_character_error_rate": _mean(
            [float(item["character_error_rate"]) for item in metrics]
        ),
        "mean_word_error_rate": _mean(
            [float(item["word_error_rate"]) for item in metrics]
        ),
        "mean_token_content_recall": _mean(
            [float(item["token_content_recall"]) for item in metrics]
        ),
        "mean_token_content_precision": _mean(
            [float(item["token_content_precision"]) for item in metrics]
        ),
        "mean_token_order_preservation": _mean(
            [float(item["token_order_preservation"]) for item in metrics]
        ),
        "aggregate_legal_critical_recall": aggregate_critical_recall,
        "critical_expected": total_critical_expected,
        "critical_matched": total_critical_matched,
        "mean_elapsed_ms": _mean(
            [float(row["elapsed_ms"]) for row in successful]
        ),
        "runtime": runtime,
        "cases": rows,
        "reference_warning": (
            "This clean/control set was admitted using native-text versus "
            "Tesseract agreement. It is valid for regression and clean-page "
            "fidelity, but is selection-biased in Tesseract's favor and must "
            "not alone select the production OCR engine."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def aggregate(inputs: list[Path], output_path: Path) -> dict[str, Any]:
    engines = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in inputs
    ]
    if not engines:
        raise RuntimeError("no engine reports supplied")

    # HARD promotion floor for the clean/control stage. This is deliberately
    # a gate, not a weighted score. Hard-page rescue evidence is still required.
    for engine in engines:
        engine["clean_stage_gate"] = {
            "passed": (
                float(engine["failure_rate"]) <= 0.01
                and engine["aggregate_legal_critical_recall"] is not None
                and float(engine["aggregate_legal_critical_recall"]) >= 0.995
            ),
            "max_failure_rate": 0.01,
            "min_aggregate_legal_critical_recall": 0.995,
        }

    eligible = [
        engine
        for engine in engines
        if engine["clean_stage_gate"]["passed"]
    ]
    eligible.sort(
        key=lambda item: (
            float(item["mean_word_error_rate"])
            if item["mean_word_error_rate"] is not None
            else float("inf"),
            float(item["mean_character_error_rate"])
            if item["mean_character_error_rate"] is not None
            else float("inf"),
            float(item["mean_elapsed_ms"])
            if item["mean_elapsed_ms"] is not None
            else float("inf"),
        )
    )
    payload = {
        "schema_version": 1,
        "benchmark_kind": "open_source_ocr_clean_control",
        "engines": engines,
        "clean_stage_eligible_engines": [item["engine"] for item in eligible],
        "clean_stage_order_by_wer": [item["engine"] for item in eligible],
        "promotion_status": "hard_rescue_benchmark_required",
        "promotion_rule": (
            "No engine may become the SCJ Principales base OCR solely from this "
            "clean/control result. Promotion requires a separate hard-page "
            "rescue set whose reference adjudication is independent of every "
            "candidate OCR engine."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score")
    score.add_argument("--manifest", type=Path, required=True)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--runtime", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)

    agg = sub.add_parser("aggregate")
    agg.add_argument("--input", type=Path, action="append", required=True)
    agg.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "score":
        payload = score_engine(
            args.manifest,
            args.predictions,
            args.runtime,
            args.output,
        )
    else:
        payload = aggregate(args.input, args.output)
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
