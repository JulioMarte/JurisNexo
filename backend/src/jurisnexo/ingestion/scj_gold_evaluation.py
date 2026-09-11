from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable


class EvaluationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


@dataclass(frozen=True, slots=True)
class CaseAnnotation:
    artifact_id: str
    start_page: int
    end_page: int
    layout_family: str
    annotated_fields: frozenset[str] = frozenset()
    decision_number: str | None = None
    docket_numbers: tuple[str, ...] = ()
    decision_date: str | None = None
    court_organ: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("artifact_id is required")
        if self.start_page <= 0 or self.end_page < self.start_page:
            raise ValueError("invalid page range")
        if not self.layout_family:
            raise ValueError("layout_family is required")

    @property
    def boundary_key(self) -> tuple[str, int, int]:
        return self.artifact_id, self.start_page, self.end_page


@dataclass(frozen=True, slots=True)
class CountMetric:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        precision = self.precision
        recall = self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True, slots=True)
class FieldMetric:
    counts: CountMetric
    annotated_cases: int
    exact_matches: int

    @property
    def exact_accuracy(self) -> float | None:
        if self.annotated_cases == 0:
            return None
        return self.exact_matches / self.annotated_cases


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    boundaries: CountMetric
    fields: dict[str, FieldMetric]
    reviewed_gold_cases: int
    exact_boundary_matches: int
    gold_cases_by_family: dict[str, int]
    matched_cases_by_family: dict[str, int]


@dataclass(frozen=True, slots=True)
class SamplePolicy:
    minimum_total_cases: int = 60
    minimum_cases_per_family: int = 8
    required_families: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PromotionThresholds:
    boundary_precision: float = 0.99
    boundary_recall: float = 0.98
    decision_number_precision: float = 0.995
    decision_number_recall: float = 0.99
    decision_date_precision: float = 0.99
    decision_date_recall: float = 0.97
    court_organ_precision: float = 0.99


@dataclass(frozen=True, slots=True)
class GateResult:
    status: EvaluationStatus
    reasons: tuple[str, ...]


@dataclass(slots=True)
class _MutableCounts:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    annotated_cases: int = 0
    exact_matches: int = 0

    def freeze(self) -> FieldMetric:
        return FieldMetric(
            counts=CountMetric(
                true_positive=self.true_positive,
                false_positive=self.false_positive,
                false_negative=self.false_negative,
            ),
            annotated_cases=self.annotated_cases,
            exact_matches=self.exact_matches,
        )


_FIELD_NAMES = frozenset(
    {
        "decision_number",
        "docket_numbers",
        "decision_date",
        "court_organ",
    }
)


def _normalize_scalar(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _normalize_set(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        normalized
        for value in values
        if (normalized := _normalize_scalar(value)) is not None
    )


def _score_scalar(expected: str | None, predicted: str | None, counts: _MutableCounts) -> None:
    counts.annotated_cases += 1
    expected_normalized = _normalize_scalar(expected)
    predicted_normalized = _normalize_scalar(predicted)

    if expected_normalized == predicted_normalized:
        counts.exact_matches += 1
        if expected_normalized is not None:
            counts.true_positive += 1
        return

    if predicted_normalized is not None:
        counts.false_positive += 1
    if expected_normalized is not None:
        counts.false_negative += 1


def _score_set(
    expected: Iterable[str], predicted: Iterable[str], counts: _MutableCounts
) -> None:
    counts.annotated_cases += 1
    expected_normalized = _normalize_set(expected)
    predicted_normalized = _normalize_set(predicted)

    if expected_normalized == predicted_normalized:
        counts.exact_matches += 1

    counts.true_positive += len(expected_normalized & predicted_normalized)
    counts.false_positive += len(predicted_normalized - expected_normalized)
    counts.false_negative += len(expected_normalized - predicted_normalized)


def evaluate_cases(
    gold: Iterable[CaseAnnotation], predicted: Iterable[CaseAnnotation]
) -> EvaluationMetrics:
    gold_list = list(gold)
    predicted_list = list(predicted)

    gold_by_key = {item.boundary_key: item for item in gold_list}
    predicted_by_key = {item.boundary_key: item for item in predicted_list}
    if len(gold_by_key) != len(gold_list):
        raise ValueError("duplicate gold boundary key")
    if len(predicted_by_key) != len(predicted_list):
        raise ValueError("duplicate predicted boundary key")

    gold_keys = set(gold_by_key)
    predicted_keys = set(predicted_by_key)
    matched_keys = gold_keys & predicted_keys

    boundary_metric = CountMetric(
        true_positive=len(matched_keys),
        false_positive=len(predicted_keys - gold_keys),
        false_negative=len(gold_keys - predicted_keys),
    )

    field_counts: dict[str, _MutableCounts] = defaultdict(_MutableCounts)
    matched_by_family: Counter[str] = Counter()
    gold_by_family: Counter[str] = Counter(item.layout_family for item in gold_list)

    for key in sorted(matched_keys):
        expected = gold_by_key[key]
        actual = predicted_by_key[key]
        matched_by_family[expected.layout_family] += 1

        unknown_fields = expected.annotated_fields - _FIELD_NAMES
        if unknown_fields:
            raise ValueError(f"unsupported annotated fields: {sorted(unknown_fields)}")

        if "decision_number" in expected.annotated_fields:
            _score_scalar(
                expected.decision_number,
                actual.decision_number,
                field_counts["decision_number"],
            )
        if "docket_numbers" in expected.annotated_fields:
            _score_set(
                expected.docket_numbers,
                actual.docket_numbers,
                field_counts["docket_numbers"],
            )
        if "decision_date" in expected.annotated_fields:
            _score_scalar(
                expected.decision_date,
                actual.decision_date,
                field_counts["decision_date"],
            )
        if "court_organ" in expected.annotated_fields:
            _score_scalar(
                expected.court_organ,
                actual.court_organ,
                field_counts["court_organ"],
            )

    return EvaluationMetrics(
        boundaries=boundary_metric,
        fields={name: counts.freeze() for name, counts in sorted(field_counts.items())},
        reviewed_gold_cases=len(gold_list),
        exact_boundary_matches=len(matched_keys),
        gold_cases_by_family=dict(sorted(gold_by_family.items())),
        matched_cases_by_family=dict(sorted(matched_by_family.items())),
    )


def _metric_below(value: float | None, threshold: float) -> bool:
    return value is None or value < threshold


def evaluate_promotion_gate(
    metrics: EvaluationMetrics,
    *,
    sample_policy: SamplePolicy = SamplePolicy(),
    thresholds: PromotionThresholds = PromotionThresholds(),
) -> GateResult:
    readiness_reasons: list[str] = []
    if metrics.reviewed_gold_cases < sample_policy.minimum_total_cases:
        readiness_reasons.append(
            "reviewed gold cases "
            f"{metrics.reviewed_gold_cases} < required {sample_policy.minimum_total_cases}"
        )

    families = sample_policy.required_families or frozenset(metrics.gold_cases_by_family)
    for family in sorted(families):
        count = metrics.gold_cases_by_family.get(family, 0)
        if count < sample_policy.minimum_cases_per_family:
            readiness_reasons.append(
                f"family {family!r} has {count} reviewed cases; "
                f"requires {sample_policy.minimum_cases_per_family}"
            )

    if readiness_reasons:
        return GateResult(
            status=EvaluationStatus.INSUFFICIENT_SAMPLE,
            reasons=tuple(readiness_reasons),
        )

    failure_reasons: list[str] = []
    boundary_precision = metrics.boundaries.precision
    boundary_recall = metrics.boundaries.recall
    if _metric_below(boundary_precision, thresholds.boundary_precision):
        failure_reasons.append(
            f"boundary precision {boundary_precision!r} < {thresholds.boundary_precision}"
        )
    if _metric_below(boundary_recall, thresholds.boundary_recall):
        failure_reasons.append(
            f"boundary recall {boundary_recall!r} < {thresholds.boundary_recall}"
        )

    required_field_thresholds = {
        "decision_number": (
            thresholds.decision_number_precision,
            thresholds.decision_number_recall,
        ),
        "decision_date": (
            thresholds.decision_date_precision,
            thresholds.decision_date_recall,
        ),
    }
    for field_name, (precision_threshold, recall_threshold) in required_field_thresholds.items():
        field_metric = metrics.fields.get(field_name)
        precision = field_metric.counts.precision if field_metric else None
        recall = field_metric.counts.recall if field_metric else None
        if _metric_below(precision, precision_threshold):
            failure_reasons.append(
                f"{field_name} precision {precision!r} < {precision_threshold}"
            )
        if _metric_below(recall, recall_threshold):
            failure_reasons.append(
                f"{field_name} recall {recall!r} < {recall_threshold}"
            )

    organ = metrics.fields.get("court_organ")
    organ_precision = organ.counts.precision if organ else None
    if _metric_below(organ_precision, thresholds.court_organ_precision):
        failure_reasons.append(
            f"court_organ precision {organ_precision!r} < "
            f"{thresholds.court_organ_precision}"
        )

    if failure_reasons:
        return GateResult(status=EvaluationStatus.FAIL, reasons=tuple(failure_reasons))
    return GateResult(status=EvaluationStatus.PASS, reasons=())
