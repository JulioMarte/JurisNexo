from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jurisnexo.ingestion.scj_gold_evaluation import (
    CaseAnnotation,
    CountMetric,
    evaluate_promotion_gate,
    evaluate_stratified,
    EvaluationMetrics,
    EvaluationReport,
    EvaluationStatus,
    FieldMetric,
    PromotionThresholds,
    SamplePolicy,
)

_SUPPORTED_REVIEW_STATUSES = {"reviewed", "adjudicated"}
_SCHEMA_VERSION = 1


def _load_jsonl(path: Path, *, require_reviewed: bool) -> list[CaseAnnotation]:
    rows: list[CaseAnnotation] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("schema_version") != _SCHEMA_VERSION:
                raise ValueError(
                    f"{path}:{line_number}: unsupported schema_version "
                    f"{payload.get('schema_version')!r}"
                )
            if require_reviewed:
                review_status = payload.get("review_status")
                if review_status not in _SUPPORTED_REVIEW_STATUSES:
                    raise ValueError(
                        f"{path}:{line_number}: review_status must be reviewed or adjudicated"
                    )

            annotated_fields = frozenset(payload.get("annotated_fields", ()))
            if not require_reviewed:
                annotated_fields = frozenset()

            rows.append(
                CaseAnnotation(
                    artifact_id=str(payload["artifact_id"]),
                    start_page=int(payload["start_page"]),
                    end_page=int(payload["end_page"]),
                    layout_family=str(payload["layout_family"]),
                    annotated_fields=annotated_fields,
                    decision_number=payload.get("decision_number"),
                    docket_numbers=tuple(payload.get("docket_numbers", ())),
                    decision_date=payload.get("decision_date"),
                    court_organ=payload.get("court_organ"),
                )
            )
    return rows


def _load_manifest(path: Path) -> tuple[SamplePolicy, PromotionThresholds, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("manifest schema_version must be 1")

    sample = payload.get("sample_policy", {})
    thresholds = payload.get("promotion_thresholds", {})
    family_minimums_payload = sample.get("family_minimums", {})
    if not isinstance(family_minimums_payload, dict):
        raise ValueError("sample_policy.family_minimums must be an object")

    sample_policy = SamplePolicy(
        minimum_total_cases=int(sample.get("minimum_total_cases", 60)),
        minimum_cases_per_family=int(sample.get("minimum_cases_per_family", 8)),
        minimum_annotated_cases_per_field=int(
            sample.get("minimum_annotated_cases_per_field", 8)
        ),
        required_families=frozenset(sample.get("required_families", ())),
        required_fields=frozenset(
            sample.get(
                "required_fields",
                ("decision_number", "decision_date", "court_organ"),
            )
        ),
        family_minimums=tuple(
            sorted((str(name), int(count)) for name, count in family_minimums_payload.items())
        ),
    )
    promotion_thresholds = PromotionThresholds(
        boundary_precision=float(thresholds.get("boundary_precision", 0.99)),
        boundary_recall=float(thresholds.get("boundary_recall", 0.98)),
        decision_number_precision=float(
            thresholds.get("decision_number_precision", 0.995)
        ),
        decision_number_recall=float(thresholds.get("decision_number_recall", 0.99)),
        decision_date_precision=float(thresholds.get("decision_date_precision", 0.99)),
        decision_date_recall=float(thresholds.get("decision_date_recall", 0.97)),
        court_organ_precision=float(thresholds.get("court_organ_precision", 0.99)),
    )
    return sample_policy, promotion_thresholds, payload


def _count_metric(metric: CountMetric) -> dict[str, Any]:
    return {
        "true_positive": metric.true_positive,
        "false_positive": metric.false_positive,
        "false_negative": metric.false_negative,
        "precision": metric.precision,
        "recall": metric.recall,
        "f1": metric.f1,
    }


def _field_metric(metric: FieldMetric) -> dict[str, Any]:
    return {
        "counts": _count_metric(metric.counts),
        "annotated_cases": metric.annotated_cases,
        "exact_matches": metric.exact_matches,
        "exact_accuracy": metric.exact_accuracy,
    }


def _metrics(metric: EvaluationMetrics) -> dict[str, Any]:
    return {
        "reviewed_gold_cases": metric.reviewed_gold_cases,
        "exact_boundary_matches": metric.exact_boundary_matches,
        "boundaries": _count_metric(metric.boundaries),
        "fields": {
            name: _field_metric(value) for name, value in sorted(metric.fields.items())
        },
        "gold_cases_by_family": metric.gold_cases_by_family,
        "matched_cases_by_family": metric.matched_cases_by_family,
    }


def _report(report: EvaluationReport) -> dict[str, Any]:
    return {
        "overall": _metrics(report.overall),
        "by_family": {
            family: _metrics(metrics) for family, metrics in sorted(report.by_family.items())
        },
    }


def _sample_policy_json(policy: SamplePolicy) -> dict[str, Any]:
    return {
        "minimum_total_cases": policy.minimum_total_cases,
        "minimum_cases_per_family": policy.minimum_cases_per_family,
        "minimum_annotated_cases_per_field": policy.minimum_annotated_cases_per_field,
        "required_families": sorted(policy.required_families),
        "required_fields": sorted(policy.required_fields),
        "family_minimums": dict(policy.family_minimums),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate SCJ parser predictions against independently reviewed gold JSONL."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predicted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--enforce-gate",
        action="store_true",
        help="Exit non-zero unless the sample is sufficient and all promotion gates pass.",
    )
    args = parser.parse_args()

    sample_policy, thresholds, manifest = _load_manifest(args.manifest)
    gold = _load_jsonl(args.gold, require_reviewed=True)
    predicted = _load_jsonl(args.predicted, require_reviewed=False)
    report = evaluate_stratified(gold, predicted)
    gate = evaluate_promotion_gate(
        report,
        sample_policy=sample_policy,
        thresholds=thresholds,
    )

    result = {
        "schema_version": _SCHEMA_VERSION,
        "dataset_id": manifest.get("dataset_id"),
        "evaluation": _report(report),
        "gate": {
            "status": gate.status.value,
            "reasons": list(gate.reasons),
        },
        "policy": {
            "sample": _sample_policy_json(sample_policy),
            "thresholds": asdict(thresholds),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.enforce_gate and gate.status is not EvaluationStatus.PASS:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
