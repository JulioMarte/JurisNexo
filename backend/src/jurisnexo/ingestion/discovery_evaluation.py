from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis


def _empty_ints() -> list[int]:
    return []


def _empty_truth_metadata() -> list[TruthMetadataValue]:
    return []


def _empty_truth_segments() -> list[TruthSegment]:
    return []


class TruthMetadataValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    value: str


class TruthSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    metadata: list[TruthMetadataValue] = Field(default_factory=_empty_truth_metadata)


class DiscoveryStructuralTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_class: str
    has_index: bool
    index_pages: list[int] = Field(default_factory=_empty_ints)
    segments: list[TruthSegment] = Field(default_factory=_empty_truth_segments)


@dataclass(frozen=True, slots=True)
class MatchMetrics:
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
    start_boundary_metrics: MatchMetrics
    end_boundary_metrics: MatchMetrics
    exact_segment_metrics: MatchMetrics
    metadata_metrics: MatchMetrics


def evaluate_discovery_structure(
    *,
    hypothesis: DocumentStructureHypothesis,
    truth: DiscoveryStructuralTruth,
) -> DiscoveryStructuralScore:
    predicted_starts = {segment.start_page for segment in hypothesis.candidate_segments}
    expected_starts = {segment.start_page for segment in truth.segments}

    predicted_ends = {
        segment.end_page
        for segment in hypothesis.candidate_segments
        if segment.end_page is not None
    }
    expected_ends = {segment.end_page for segment in truth.segments}

    predicted_segments = {
        (segment.start_page, segment.end_page)
        for segment in hypothesis.candidate_segments
        if segment.end_page is not None
    }
    expected_segments = {(segment.start_page, segment.end_page) for segment in truth.segments}

    predicted_metadata = {
        (
            segment.start_page,
            segment.end_page,
            item.field_name.casefold(),
            _normalize_value(item.value),
        )
        for segment in hypothesis.candidate_segments
        if segment.end_page is not None
        for item in segment.metadata
    }
    expected_metadata = {
        (
            segment.start_page,
            segment.end_page,
            item.field_name.casefold(),
            _normalize_value(item.value),
        )
        for segment in truth.segments
        for item in segment.metadata
    }

    return DiscoveryStructuralScore(
        artifact_class_correct=hypothesis.artifact_class == truth.artifact_class,
        has_index_correct=hypothesis.has_index == truth.has_index,
        index_pages_exact=set(hypothesis.index_page_candidates) == set(truth.index_pages),
        start_boundary_metrics=_match_metrics(predicted_starts, expected_starts),
        end_boundary_metrics=_match_metrics(predicted_ends, expected_ends),
        exact_segment_metrics=_match_metrics(predicted_segments, expected_segments),
        metadata_metrics=_match_metrics(predicted_metadata, expected_metadata),
    )


def _match_metrics(
    predicted: AbstractSet[object],
    expected: AbstractSet[object],
) -> MatchMetrics:
    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    return MatchMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
    )


def _normalize_value(value: str) -> str:
    return " ".join(value.split()).casefold()


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
