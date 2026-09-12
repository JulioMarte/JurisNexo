from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurisnexo.ingestion.decision_reconstruction import (
    DecisionBoundary,
    reconstruct_source_faithful_decision,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def test_reconstruction_includes_only_approved_boundary_pages() -> None:
    environment = DocumentEnvironment(
        (
            "PRIOR DECISION TAIL",
            "TARGET DECISION HEADER",
            "TARGET DECISION BODY",
            "NEXT DECISION HEADER",
        ),
        printed_page_numbers=(100, 101, 102, 103),
        source_references=("src:100", "src:101", "src:102", "src:103"),
    )

    result = reconstruct_source_faithful_decision(
        environment=environment,
        boundary=DecisionBoundary(start_view_page=2, end_view_page=3),
    )

    assert [page.view_page for page in result.pages] == [2, 3]
    assert [page.printed_page for page in result.pages] == [101, 102]
    assert "TARGET DECISION HEADER" in result.ordered_text
    assert "TARGET DECISION BODY" in result.ordered_text
    assert "PRIOR DECISION TAIL" not in result.ordered_text
    assert "NEXT DECISION HEADER" not in result.ordered_text


def test_reconstruction_uses_full_stored_text_not_agent_context_clip() -> None:
    long_text = "A" * 900
    environment = DocumentEnvironment((long_text,), max_page_chars=500)

    agent_view = environment.get_page(1)
    result = reconstruct_source_faithful_decision(
        environment=environment,
        boundary=DecisionBoundary(start_view_page=1, end_view_page=1),
    )

    assert agent_view.truncated is True
    assert len(agent_view.text) == 500
    assert result.pages[0].text == long_text
    assert result.pages[0].char_end == 900
    assert result.ordered_text == long_text


def test_empty_source_page_remains_explicitly_unresolved() -> None:
    environment = DocumentEnvironment(
        ("HEADER", "   ", "OUTCOME"),
        printed_page_numbers=(10, 11, 12),
    )

    result = reconstruct_source_faithful_decision(
        environment=environment,
        boundary=DecisionBoundary(start_view_page=1, end_view_page=3),
    )

    assert result.pages[1].readability == "empty_source_page"
    assert len(result.unresolved_regions) == 1
    assert result.unresolved_regions[0].view_page == 2
    assert result.unresolved_regions[0].printed_page == 11
    assert "inventing content" in result.unresolved_regions[0].explanation


def test_reconstruction_preserves_page_provenance_and_exact_ordered_text() -> None:
    environment = DocumentEnvironment(
        ("first", "second"),
        printed_page_numbers=(77, 78),
        source_references=("scan:left", "scan:right"),
    )

    result = reconstruct_source_faithful_decision(
        environment=environment,
        boundary=DecisionBoundary(start_view_page=1, end_view_page=2),
    )

    assert result.ordered_text == "first\n\nsecond"
    assert result.page_joiner == "\n\n"
    assert result.pages[0].source_reference == "scan:left"
    assert result.pages[1].source_reference == "scan:right"


def test_reverse_boundary_is_rejected() -> None:
    with pytest.raises(ValidationError, match="end_view_page must be"):
        DecisionBoundary(start_view_page=5, end_view_page=4)
