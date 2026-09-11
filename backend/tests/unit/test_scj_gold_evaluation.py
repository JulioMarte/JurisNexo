import pytest

from jurisnexo.ingestion.scj_gold_evaluation import (
    CaseAnnotation,
    EvaluationStatus,
    PromotionThresholds,
    SamplePolicy,
    evaluate_cases,
    evaluate_promotion_gate,
)

pytestmark = pytest.mark.unit


ALL_FIELDS = frozenset(
    {"decision_number", "docket_numbers", "decision_date", "court_organ"}
)


def case(
    *,
    artifact: str = "fixture.pdf",
    start: int,
    end: int,
    family: str = "sentence",
    number: str | None = "SCJ-PS-25-0001",
    dockets: tuple[str, ...] = ("001-2025",),
    decision_date: str | None = "2025-01-31",
    organ: str | None = "Primera Sala",
    annotated_fields: frozenset[str] = ALL_FIELDS,
) -> CaseAnnotation:
    return CaseAnnotation(
        artifact_id=artifact,
        start_page=start,
        end_page=end,
        layout_family=family,
        annotated_fields=annotated_fields,
        decision_number=number,
        docket_numbers=dockets,
        decision_date=decision_date,
        court_organ=organ,
    )


def test_boundary_metrics_are_exact_span_metrics() -> None:
    gold = [case(start=10, end=12), case(start=20, end=25)]
    predicted = [case(start=10, end=12), case(start=20, end=24), case(start=30, end=31)]

    metrics = evaluate_cases(gold, predicted)

    assert metrics.boundaries.true_positive == 1
    assert metrics.boundaries.false_positive == 2
    assert metrics.boundaries.false_negative == 1
    assert metrics.boundaries.precision == pytest.approx(1 / 3)
    assert metrics.boundaries.recall == pytest.approx(1 / 2)


def test_scalar_wrong_value_counts_as_false_positive_and_false_negative() -> None:
    gold = [case(start=1, end=2, number="SCJ-PS-25-0001")]
    predicted = [case(start=1, end=2, number="SCJ-PS-25-9999")]

    metric = evaluate_cases(gold, predicted).fields["decision_number"]

    assert metric.counts.true_positive == 0
    assert metric.counts.false_positive == 1
    assert metric.counts.false_negative == 1
    assert metric.exact_accuracy == 0.0


def test_scalar_null_is_a_real_reviewed_absence_not_unannotated() -> None:
    gold = [
        case(
            start=1,
            end=1,
            number=None,
            annotated_fields=frozenset({"decision_number"}),
        )
    ]
    predicted = [
        case(
            start=1,
            end=1,
            number=None,
            annotated_fields=frozenset(),
        )
    ]

    metric = evaluate_cases(gold, predicted).fields["decision_number"]

    assert metric.annotated_cases == 1
    assert metric.exact_matches == 1
    assert metric.exact_accuracy == 1.0
    assert metric.counts.precision is None
    assert metric.counts.recall is None


def test_unannotated_field_does_not_enter_metric_denominator() -> None:
    gold = [
        case(
            start=1,
            end=1,
            number="WRONG IF SCORED",
            annotated_fields=frozenset({"decision_date"}),
        )
    ]
    predicted = [case(start=1, end=1, number="DIFFERENT")]

    metrics = evaluate_cases(gold, predicted)

    assert "decision_number" not in metrics.fields
    assert metrics.fields["decision_date"].exact_accuracy == 1.0


def test_docket_metric_is_set_based_and_order_independent() -> None:
    gold = [case(start=1, end=1, dockets=("A-1", "B-2"))]
    predicted = [case(start=1, end=1, dockets=("b-2", "A-1"))]

    metric = evaluate_cases(gold, predicted).fields["docket_numbers"]

    assert metric.counts.true_positive == 2
    assert metric.counts.false_positive == 0
    assert metric.counts.false_negative == 0
    assert metric.exact_accuracy == 1.0


def test_docket_metric_exposes_extra_and_missing_identifiers() -> None:
    gold = [case(start=1, end=1, dockets=("A-1", "B-2"))]
    predicted = [case(start=1, end=1, dockets=("A-1", "C-3"))]

    metric = evaluate_cases(gold, predicted).fields["docket_numbers"]

    assert metric.counts.true_positive == 1
    assert metric.counts.false_positive == 1
    assert metric.counts.false_negative == 1
    assert metric.exact_accuracy == 0.0


def test_metadata_metrics_are_conditioned_on_exact_boundary_matches() -> None:
    gold = [case(start=10, end=12)]
    predicted = [case(start=10, end=11)]

    metrics = evaluate_cases(gold, predicted)

    assert metrics.exact_boundary_matches == 0
    assert metrics.fields == {}


def test_duplicate_boundary_keys_are_rejected() -> None:
    duplicate = case(start=1, end=1)

    with pytest.raises(ValueError, match="duplicate gold boundary key"):
        evaluate_cases([duplicate, duplicate], [duplicate])


def test_unknown_annotated_field_is_rejected() -> None:
    gold = [
        case(
            start=1,
            end=1,
            annotated_fields=frozenset({"not_a_supported_field"}),
        )
    ]

    with pytest.raises(ValueError, match="unsupported annotated fields"):
        evaluate_cases(gold, [case(start=1, end=1)])


def test_small_perfect_sample_cannot_pass_promotion_gate() -> None:
    gold = [case(start=index, end=index, family="family_a") for index in range(1, 8)]
    metrics = evaluate_cases(gold, gold)

    gate = evaluate_promotion_gate(
        metrics,
        sample_policy=SamplePolicy(
            minimum_total_cases=20,
            minimum_cases_per_family=5,
            required_families=frozenset({"family_a", "family_b"}),
        ),
    )

    assert gate.status is EvaluationStatus.INSUFFICIENT_SAMPLE
    assert any("reviewed gold cases" in reason for reason in gate.reasons)
    assert any("family 'family_b'" in reason for reason in gate.reasons)


def test_sufficient_perfect_sample_can_pass_strict_gate() -> None:
    gold = [
        case(start=index, end=index, family="family_a") for index in range(1, 6)
    ] + [
        case(start=index, end=index, family="family_b") for index in range(10, 15)
    ]
    metrics = evaluate_cases(gold, gold)

    gate = evaluate_promotion_gate(
        metrics,
        sample_policy=SamplePolicy(
            minimum_total_cases=10,
            minimum_cases_per_family=5,
            required_families=frozenset({"family_a", "family_b"}),
        ),
    )

    assert gate.status is EvaluationStatus.PASS
    assert gate.reasons == ()


def test_sufficient_sample_fails_when_boundary_or_field_threshold_missed() -> None:
    gold = [case(start=index, end=index) for index in range(1, 11)]
    predicted = list(gold)
    predicted[-1] = case(start=10, end=10, decision_date="2024-12-31")
    metrics = evaluate_cases(gold, predicted)

    gate = evaluate_promotion_gate(
        metrics,
        sample_policy=SamplePolicy(minimum_total_cases=10, minimum_cases_per_family=1),
        thresholds=PromotionThresholds(decision_date_precision=0.99),
    )

    assert gate.status is EvaluationStatus.FAIL
    assert any("decision_date precision" in reason for reason in gate.reasons)
