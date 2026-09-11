from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis


def _empty_ints() -> list[int]:
    return []


class DiscoveryStructuralTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_class: str
    has_index: bool
    index_pages: list[int] = Field(default_factory=_empty_ints)
    segment_start_pages: list[int] = Field(default_factory=_empty_ints)


@dataclass(frozen=True, slots=True)
class BoundaryMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class DiscoveryStructuralScore:
    artifact_class_correct: bool
    has_index_correct: bool
    index_pages_exact: bool
    boundary_metrics: BoundaryMetrics


def evaluate_discovery_structure(
    *,
    hypothesis: DocumentStructureHypothesis,
    truth: DiscoveryStructuralTruth,
) -> DiscoveryStructuralScore:
    predicted_starts = {segment.start_page for segment in hypothesis.candidate_segments}
    expected_starts = set(truth.segment_start_pages)
    true_positive = len(predicted_starts & expected_starts)
    false_positive = len(predicted_starts - expected_starts)
    false_negative = len(expected_starts - predicted_starts)

    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    f1 = _f1(precision, recall)

    return DiscoveryStructuralScore(
        artifact_class_correct=hypothesis.artifact_class == truth.artifact_class,
        has_index_correct=hypothesis.has_index == truth.has_index,
        index_pages_exact=set(hypothesis.index_page_candidates) == set(truth.index_pages),
        boundary_metrics=BoundaryMetrics(
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            precision=precision,
            recall=recall,
            f1=f1,
        ),
    )


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
