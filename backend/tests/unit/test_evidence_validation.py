from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.evidence_validation import (
    EvidenceValidationError,
    validate_index_reference_evidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _hypothesis(*, evidence_pages: list[dict[str, object]]) -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis.model_validate(
        {
            "artifact_class": "bulletin",
            "family_name_candidate": "legacy_bulletin_candidate",
            "structure_confidence": 0.8,
            "has_index": True,
            "index_page_candidates": [1],
            "candidate_segments": [],
            "segmentation_hypotheses": [],
            "metadata_hypotheses": [],
            "index_reference_investigations": [
                {
                    "reference_as_printed": 353,
                    "expected_description": "Pelayo Fernández decision",
                    "resolution_status": "confirmed_nearby",
                    "observed_decision_start_printed_page": 354,
                    "evidence_pages": evidence_pages,
                    "observed_description": "Expected decision starts on printed page 354",
                    "explanation": "Printed page 353 continues the prior matter.",
                    "confidence": 0.93,
                }
            ],
            "anomalies": [],
            "recommended_next_actions": [],
            "status": "candidate",
        }
    )


def _environment() -> DocumentEnvironment:
    return DocumentEnvironment(
        ("continuation", "SENTENCIA Pelayo Fernández"),
        printed_page_numbers=(353, 354),
        source_references=(
            "physical_pages=173,174; side=right",
            "physical_pages=175,176; side=left",
        ),
    )


def test_accepts_exact_view_printed_and_source_correspondence() -> None:
    hypothesis = _hypothesis(
        evidence_pages=[
            {
                "view_page": 1,
                "printed_page": 353,
                "role": "claimed_destination",
                "source_reference": "physical_pages=173,174; side=right",
            },
            {
                "view_page": 2,
                "printed_page": 354,
                "role": "observed_content",
                "source_reference": "physical_pages=175,176; side=left",
            },
        ]
    )

    validate_index_reference_evidence(hypothesis=hypothesis, environment=_environment())


def test_rejects_invented_view_page() -> None:
    hypothesis = _hypothesis(
        evidence_pages=[{"view_page": 999, "printed_page": 354}]
    )

    with pytest.raises(EvidenceValidationError, match="not in the document environment"):
        validate_index_reference_evidence(hypothesis=hypothesis, environment=_environment())


def test_rejects_wrong_view_to_printed_mapping() -> None:
    hypothesis = _hypothesis(
        evidence_pages=[{"view_page": 1, "printed_page": 354}]
    )

    with pytest.raises(EvidenceValidationError, match="resolves to printed page 353"):
        validate_index_reference_evidence(hypothesis=hypothesis, environment=_environment())


def test_rejects_claim_when_printed_page_is_unresolved() -> None:
    environment = DocumentEnvironment(("SENTENCIA",), printed_page_numbers=(None,))
    hypothesis = _hypothesis(
        evidence_pages=[{"view_page": 1, "printed_page": 354}]
    )

    with pytest.raises(EvidenceValidationError, match="no resolved printed page"):
        validate_index_reference_evidence(hypothesis=hypothesis, environment=environment)


def test_rejects_wrong_source_provenance() -> None:
    hypothesis = _hypothesis(
        evidence_pages=[
            {
                "view_page": 2,
                "printed_page": 354,
                "source_reference": "physical_pages=999; side=left",
            }
        ]
    )

    with pytest.raises(EvidenceValidationError, match="source provenance does not match"):
        validate_index_reference_evidence(hypothesis=hypothesis, environment=_environment())
