from __future__ import annotations

import pytest

from jurisnexo.normalization.jev_calibration import (
    BinaryRoutingObservation,
    assess_promotion_readiness,
    brier_score,
    evaluate_frozen_candidate_on_holdout,
    select_candidate_threshold,
)


def _o(
    record_id: str,
    *,
    positive: bool,
    probability: float,
) -> BinaryRoutingObservation:
    return BinaryRoutingObservation(
        record_id=record_id,
        expected_positive=positive,
        probability=probability,
    )


def test_candidate_threshold_prioritizes_false_negative_avoidance() -> None:
    calibration = (
        _o("p1", positive=True, probability=0.80),
        _o("p2", positive=True, probability=0.55),
        _o("n1", positive=False, probability=0.40),
        _o("n2", positive=False, probability=0.10),
    )

    candidate = select_candidate_threshold(
        calibration,
        thresholds=(0.25, 0.50, 0.75),
    )

    assert candidate.threshold == 0.50
    assert candidate.calibration.false_negative_rate == 0.0
    assert candidate.calibration.false_positive_rate == 0.0


def test_holdout_uses_frozen_threshold_without_reselection() -> None:
    calibration = (
        _o("p1", positive=True, probability=0.70),
        _o("n1", positive=False, probability=0.20),
    )
    candidate = select_candidate_threshold(
        calibration,
        thresholds=(0.25, 0.50, 0.75),
    )
    assert candidate.threshold == 0.50

    holdout = (
        _o("p2", positive=True, probability=0.45),
        _o("n2", positive=False, probability=0.10),
    )
    metrics = evaluate_frozen_candidate_on_holdout(
        candidate,
        holdout,
    )

    assert metrics.threshold == 0.50
    assert metrics.false_negative_rate == 1.0
    assert metrics.false_positive_rate == 0.0


def test_brier_score_penalizes_overconfident_wrong_predictions() -> None:
    good = (
        _o("p", positive=True, probability=0.95),
        _o("n", positive=False, probability=0.05),
    )
    bad = (
        _o("p", positive=True, probability=0.05),
        _o("n", positive=False, probability=0.95),
    )

    assert brier_score(good) == pytest.approx(0.0025)
    assert brier_score(bad) == pytest.approx(0.9025)



def test_promotion_readiness_rejects_tiny_green_sample() -> None:
    calibration = (
        _o("p1", positive=True, probability=0.95),
        _o("n1", positive=False, probability=0.05),
    )
    candidate = select_candidate_threshold(
        calibration,
        thresholds=(0.50,),
    )
    holdout = (
        _o("p2", positive=True, probability=0.95),
        _o("n2", positive=False, probability=0.05),
    )
    holdout_metrics = evaluate_frozen_candidate_on_holdout(
        candidate,
        holdout,
    )
    assessment = assess_promotion_readiness(
        calibration=candidate.calibration,
        holdout=holdout_metrics,
        brier=brier_score((*calibration, *holdout)),
    )

    assert not assessment.eligible
    assert any("sample" in reason for reason in assessment.reasons)


def test_promotion_readiness_accepts_large_well_calibrated_evidence() -> None:
    calibration = tuple(
        _o(f"cp{index}", positive=True, probability=0.95)
        for index in range(25)
    ) + tuple(
        _o(f"cn{index}", positive=False, probability=0.05)
        for index in range(25)
    )
    candidate = select_candidate_threshold(
        calibration,
        thresholds=(0.50,),
    )
    holdout = tuple(
        _o(f"hp{index}", positive=True, probability=0.95)
        for index in range(25)
    ) + tuple(
        _o(f"hn{index}", positive=False, probability=0.05)
        for index in range(25)
    )
    holdout_metrics = evaluate_frozen_candidate_on_holdout(
        candidate,
        holdout,
    )
    assessment = assess_promotion_readiness(
        calibration=candidate.calibration,
        holdout=holdout_metrics,
        brier=brier_score((*calibration, *holdout)),
    )

    assert assessment.eligible
    assert assessment.reasons == ()
