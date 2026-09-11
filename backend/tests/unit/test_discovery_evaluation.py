from __future__ import annotations

import pytest

from jurisnexo.ingestion.discovery_evaluation import (
    DiscoveryStructuralTruth,
    evaluate_discovery_structure,
)
from jurisnexo.ingestion.document_discovery import CandidateSegment, DocumentStructureHypothesis

pytestmark = pytest.mark.unit


def _hypothesis(*starts: int) -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis(
        artifact_class="bulletin",
        family_name_candidate="legacy_bulletin",
        structure_confidence=0.9,
        has_index=True,
        index_page_candidates=[1],
        candidate_segments=[
            CandidateSegment(
                start_page=start,
                end_page=None,
                evidence_pages=[start],
                confidence=0.9,
            )
            for start in starts
        ],
        status="candidate",
    )


def test_boundary_metrics_reward_exact_candidate_starts() -> None:
    score = evaluate_discovery_structure(
        hypothesis=_hypothesis(5, 12, 20),
        truth=DiscoveryStructuralTruth(
            artifact_class="bulletin",
            has_index=True,
            index_pages=[1],
            segment_start_pages=[5, 12, 20],
        ),
    )

    assert score.artifact_class_correct is True
    assert score.has_index_correct is True
    assert score.index_pages_exact is True
    assert score.boundary_metrics.precision == 1.0
    assert score.boundary_metrics.recall == 1.0
    assert score.boundary_metrics.f1 == 1.0


def test_boundary_metrics_penalize_missing_and_extra_starts() -> None:
    score = evaluate_discovery_structure(
        hypothesis=_hypothesis(5, 13, 20),
        truth=DiscoveryStructuralTruth(
            artifact_class="bulletin",
            has_index=True,
            index_pages=[1],
            segment_start_pages=[5, 12, 20],
        ),
    )

    assert score.boundary_metrics.true_positive == 2
    assert score.boundary_metrics.false_positive == 1
    assert score.boundary_metrics.false_negative == 1
    assert score.boundary_metrics.precision == pytest.approx(2 / 3)
    assert score.boundary_metrics.recall == pytest.approx(2 / 3)
    assert score.boundary_metrics.f1 == pytest.approx(2 / 3)
