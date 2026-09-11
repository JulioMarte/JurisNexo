from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError

pytestmark = pytest.mark.unit


def test_environment_uses_one_based_physical_pages() -> None:
    environment = DocumentEnvironment(("INDEX", "SECOND PAGE", "THIRD PAGE"))

    assert environment.page_count == 3
    assert environment.get_page(1).text == "INDEX"
    assert environment.get_page(3).text == "THIRD PAGE"

    with pytest.raises(DocumentEnvironmentError):
        environment.get_page(0)


def test_literal_search_returns_page_provenance() -> None:
    environment = DocumentEnvironment(
        (
            "INDICE\nSentencia A ..... página 4",
            "Introducción",
            "Otra página",
            "SENTENCIA DEL 4 DE MARZO DE 1974\nExpediente núm. 1234",
        )
    )

    hits = environment.search_text("sentencia")

    assert [hit.page_number for hit in hits] == [1, 4]
    assert "Sentencia A" in hits[0].snippet


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
