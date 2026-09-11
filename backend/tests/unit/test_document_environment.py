from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError

pytestmark = pytest.mark.unit


def test_environment_uses_one_based_view_pages() -> None:
    environment = DocumentEnvironment(("INDEX", "SECOND PAGE", "THIRD PAGE"))

    assert environment.page_count == 3
    assert environment.get_page(1).text == "INDEX"
    assert environment.get_page(3).text == "THIRD PAGE"
    assert environment.supports_printed_page_lookup is False

    with pytest.raises(DocumentEnvironmentError):
        environment.get_page(0)


def test_literal_search_returns_view_and_source_provenance() -> None:
    environment = DocumentEnvironment(
        (
            "INDICE\nSentencia A ..... página 183",
            "Introducción",
            "SENTENCIA DEL 6 DE FEBRERO DE 1980\nMateria: Correccional",
        ),
        printed_page_numbers=(None, None, 183),
        source_references=(
            "physical_pages=3; side=left",
            "physical_pages=4; side=left",
            "physical_pages=5,6; side=right",
        ),
    )

    hits = environment.search_text("sentencia")

    assert [hit.page_number for hit in hits] == [1, 3]
    assert "Sentencia A" in hits[0].snippet
    assert hits[0].printed_page_number is None
    assert hits[2 - 1].printed_page_number == 183
    assert hits[1].source_reference == "physical_pages=5,6; side=right"


def test_printed_page_lookup_returns_resolved_page_with_provenance() -> None:
    environment = DocumentEnvironment(
        ("SUMARIO", "SENTENCIA"),
        printed_page_numbers=(None, 183),
        source_references=("physical_pages=3", "physical_pages=5,6; side=right"),
    )

    page = environment.get_printed_page(183)

    assert page.page_number == 2
    assert page.printed_page_number == 183
    assert page.source_reference == "physical_pages=5,6; side=right"

    with pytest.raises(DocumentEnvironmentError, match="184 is not resolved"):
        environment.get_printed_page(184)


def test_printed_page_lookup_requires_unique_resolved_numbers() -> None:
    with pytest.raises(DocumentEnvironmentError, match="must be unique"):
        DocumentEnvironment(
            ("first", "second"),
            printed_page_numbers=(183, 183),
        )


def test_even_sampling_is_deterministic_and_bounded() -> None:
    environment = DocumentEnvironment(tuple(f"page {index}" for index in range(1, 11)))

    first = environment.sample_pages("even", 4)
    second = environment.sample_pages("even", 4)

    assert [page.page_number for page in first] == [1, 4, 7, 10]
    assert first == second


def test_page_text_is_clipped_before_leaving_environment() -> None:
    environment = DocumentEnvironment(("x" * 1_000,), max_page_chars=500)

    page = environment.get_page(1)

    assert len(page.text) == 500
    assert page.truncated is True
