from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurisnexo.ingestion.document_discovery import (
    DocumentStructureHypothesis,
    IndexReferenceInvestigation,
)

pytestmark = pytest.mark.unit


def _base_investigation() -> dict[str, object]:
    return {
        "reference_as_printed": 353,
        "expected_description": "Pelayo Fernández decision",
        "resolution_status": "confirmed_nearby",
        "observed_decision_start_printed_page": 354,
        "observed_description": "Expected decision starts on printed page 354",
        "explanation": "Printed page 353 continues the prior matter.",
        "confidence": 0.93,
    }


def test_schema_uses_explicit_page_correspondence_not_parallel_arrays() -> None:
    schema = DocumentStructureHypothesis.model_json_schema()
    serialized = str(schema)

    assert "evidence_pages" in serialized
    assert "view_page" in serialized
    assert "printed_page" in serialized
    assert "evidence_printed_pages" not in serialized
    assert "evidence_view_pages" not in serialized


def test_typed_evidence_preserves_view_to_printed_page_mapping() -> None:
    payload = _base_investigation()
    payload["evidence_pages"] = [
        {
            "view_page": 2,
            "printed_page": 353,
            "role": "claimed_destination",
            "source_reference": "physical_pages=173,174; side=right",
        },
        {
            "view_page": 3,
            "printed_page": 354,
            "role": "observed_content",
            "source_reference": "physical_pages=175,176; side=left",
        },
    ]

    investigation = IndexReferenceInvestigation.model_validate(payload)

    assert investigation.evidence_pages[0].view_page == 2
    assert investigation.evidence_pages[0].printed_page == 353
    assert investigation.evidence_pages[1].view_page == 3
    assert investigation.evidence_pages[1].printed_page == 354


def test_legacy_parallel_arrays_are_normalized_only_when_unambiguous() -> None:
    payload = _base_investigation()
    payload["evidence_printed_pages"] = [353, 354]
    payload["evidence_view_pages"] = [2, 3]

    investigation = IndexReferenceInvestigation.model_validate(payload)

    assert [(item.view_page, item.printed_page) for item in investigation.evidence_pages] == [
        (2, 353),
        (3, 354),
    ]
    dumped = investigation.model_dump()
    assert "evidence_printed_pages" not in dumped
    assert "evidence_view_pages" not in dumped


def test_legacy_parallel_arrays_reject_missing_correspondence() -> None:
    payload = _base_investigation()
    payload["evidence_printed_pages"] = [353, 354]
    payload["evidence_view_pages"] = [2]

    with pytest.raises(ValidationError, match="must have equal length"):
        IndexReferenceInvestigation.model_validate(payload)


def test_confirmed_resolution_requires_observed_start_in_evidence() -> None:
    payload = _base_investigation()
    payload["evidence_pages"] = [
        {"view_page": 2, "printed_page": 353, "role": "claimed_destination"}
    ]

    with pytest.raises(ValidationError, match="observed decision start"):
        IndexReferenceInvestigation.model_validate(payload)


def test_duplicate_page_correspondence_is_rejected() -> None:
    payload = _base_investigation()
    payload["evidence_pages"] = [
        {"view_page": 3, "printed_page": 354, "role": "observed_content"},
        {"view_page": 3, "printed_page": 354, "role": "neighbor_context"},
    ]

    with pytest.raises(ValidationError, match="duplicate view/printed"):
        IndexReferenceInvestigation.model_validate(payload)
