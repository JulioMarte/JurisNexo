from __future__ import annotations

import pytest

from jurisnexo.ingestion.discovery_evaluation import (
    DiscoveryStructuralTruth,
    TruthMetadataValue,
    TruthSegment,
    evaluate_discovery_structure,
)
from jurisnexo.ingestion.document_discovery import (
    CandidateMetadataValue,
    CandidateSegment,
    DocumentStructureHypothesis,
)

pytestmark = pytest.mark.unit


def _hypothesis(*segments: CandidateSegment) -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis(
        artifact_class="bulletin",
        family_name_candidate="legacy_bulletin",
        structure_confidence=0.9,
        has_index=True,
        index_page_candidates=[1],
        candidate_segments=list(segments),
        status="candidate",
    )


def _segment(
    start: int,
    end: int | None,
    *,
    docket: str | None = None,
) -> CandidateSegment:
    metadata = []
    if docket is not None:
        metadata.append(
            CandidateMetadataValue(
                field_name="docket_number",
                value=docket,
                evidence_pages=[start],
                confidence=0.9,
            )
        )
    return CandidateSegment(
        start_page=start,
        end_page=end,
        evidence_pages=[start],
        metadata=metadata,
        confidence=0.9,
    )


def _truth() -> DiscoveryStructuralTruth:
    return DiscoveryStructuralTruth(
        artifact_class="bulletin",
        has_index=True,
        index_pages=[1],
        segments=[
            TruthSegment(
                start_page=5,
                end_page=11,
                metadata=[TruthMetadataValue(field_name="docket_number", value="A-101")],
            ),
            TruthSegment(
                start_page=12,
                end_page=19,
                metadata=[TruthMetadataValue(field_name="docket_number", value="B-202")],
            ),
            TruthSegment(start_page=20, end_page=25),
        ],
    )


def test_metrics_reward_exact_segments_and_metadata() -> None:
    score = evaluate_discovery_structure(
        hypothesis=_hypothesis(
            _segment(5, 11, docket="A-101"),
            _segment(12, 19, docket="B-202"),
            _segment(20, 25),
        ),
        truth=_truth(),
    )

    assert score.artifact_class_correct is True
    assert score.has_index_correct is True
    assert score.index_pages_exact is True
    assert score.start_boundary_metrics.f1 == 1.0
    assert score.end_boundary_metrics.f1 == 1.0
    assert score.exact_segment_metrics.f1 == 1.0
    assert score.metadata_metrics.f1 == 1.0


def test_metrics_expose_correct_starts_but_wrong_ends() -> None:
    score = evaluate_discovery_structure(
        hypothesis=_hypothesis(
            _segment(5, 10, docket="A-101"),
            _segment(12, 19, docket="B-202"),
            _segment(20, 25),
        ),
        truth=_truth(),
    )

    assert score.start_boundary_metrics.f1 == 1.0
    assert score.end_boundary_metrics.true_positive == 2
    assert score.end_boundary_metrics.false_positive == 1
    assert score.end_boundary_metrics.false_negative == 1
    assert score.exact_segment_metrics.true_positive == 2
    assert score.exact_segment_metrics.f1 == pytest.approx(2 / 3)
    assert score.metadata_metrics.true_positive == 1
    assert score.metadata_metrics.false_positive == 1
    assert score.metadata_metrics.false_negative == 1


def test_metadata_metrics_penalize_wrong_value_without_hiding_structure() -> None:
    score = evaluate_discovery_structure(
        hypothesis=_hypothesis(
            _segment(5, 11, docket="WRONG"),
            _segment(12, 19, docket="B-202"),
            _segment(20, 25),
        ),
        truth=_truth(),
    )

    assert score.exact_segment_metrics.f1 == 1.0
    assert score.metadata_metrics.true_positive == 1
    assert score.metadata_metrics.false_positive == 1
    assert score.metadata_metrics.false_negative == 1
    assert score.metadata_metrics.f1 == pytest.approx(0.5)
