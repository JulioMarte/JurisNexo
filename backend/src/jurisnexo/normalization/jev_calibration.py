from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BinaryRoutingObservation:
    record_id: str
    expected_positive: bool
    probability: float


@dataclass(frozen=True, slots=True)
class ThresholdMetrics:
    threshold: float
    true_positive_rate: float
    false_negative_rate: float
    false_positive_rate: float
    true_negative_rate: float
    positive_count: int
    negative_count: int


@dataclass(frozen=True, slots=True)
class ThresholdCandidate:
    threshold: float
    calibration: ThresholdMetrics


def evaluate_threshold(
    observations: tuple[BinaryRoutingObservation, ...],
    *,
    threshold: float,
) -> ThresholdMetrics:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must stay within [0, 1]")

    positives = tuple(item for item in observations if item.expected_positive)
    negatives = tuple(item for item in observations if not item.expected_positive)
    if not positives or not negatives:
        raise ValueError("threshold evaluation requires positive and negative cases")

    true_positives = sum(item.probability >= threshold for item in positives)
    false_negatives = len(positives) - true_positives
    false_positives = sum(item.probability >= threshold for item in negatives)
    true_negatives = len(negatives) - false_positives

    return ThresholdMetrics(
        threshold=threshold,
        true_positive_rate=true_positives / len(positives),
        false_negative_rate=false_negatives / len(positives),
        false_positive_rate=false_positives / len(negatives),
        true_negative_rate=true_negatives / len(negatives),
        positive_count=len(positives),
        negative_count=len(negatives),
    )


def select_candidate_threshold(
    calibration: tuple[BinaryRoutingObservation, ...],
    *,
    thresholds: tuple[float, ...],
) -> ThresholdCandidate:
    if not thresholds:
        raise ValueError("at least one threshold candidate is required")

    evaluated = tuple(
        evaluate_threshold(calibration, threshold=threshold)
        for threshold in thresholds
    )
    # Legal-evidence routing prioritizes false-negative avoidance first.
    # Among equal recall, choose fewer false positives/escalations. If still
    # tied, prefer the higher threshold to avoid unnecessary model spend.
    best = min(
        evaluated,
        key=lambda item: (
            item.false_negative_rate,
            item.false_positive_rate,
            -item.threshold,
        ),
    )
    return ThresholdCandidate(
        threshold=best.threshold,
        calibration=best,
    )


def evaluate_frozen_candidate_on_holdout(
    candidate: ThresholdCandidate,
    holdout: tuple[BinaryRoutingObservation, ...],
) -> ThresholdMetrics:
    return evaluate_threshold(
        holdout,
        threshold=candidate.threshold,
    )


def brier_score(
    observations: tuple[BinaryRoutingObservation, ...],
) -> float:
    if not observations:
        raise ValueError("Brier score requires at least one observation")
    return sum(
        (
            item.probability
            - (1.0 if item.expected_positive else 0.0)
        )
        ** 2
        for item in observations
    ) / len(observations)
