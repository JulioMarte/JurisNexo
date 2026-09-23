from __future__ import annotations

import pytest

from jurisnexo.normalization.gold import (
    CriticalCategoryScore,
    TextFidelityScore,
    score_document_fidelity,
    score_text_fidelity,
)


def test_gold_scoring_measures_generic_and_legal_critical_fidelity() -> None:
    expected = (
        "SENTENCIA TC/0001/26. Expediente TC-04-2025-0258. "
        "Artículo 53 de la Ley núm. 137-11. "
        "Fecha 31/01/2026. Monto RD$ 12,500.00."
    )
    candidate = (
        "SENTENCIA TC/0001/26. Expediente TC-04-2025-0258. "
        "Articulo 53 de la Ley num. 137-11. "
        "Fecha 31/01/2026. Monto RD$ 12,500.00."
    )

    score = score_text_fidelity(
        expected_text=expected,
        candidate_text=candidate,
        required_spans=("TC/0001/26", "TC-04-2025-0258"),
    )

    assert score.character_error_rate > 0
    assert score.word_error_rate > 0
    assert score.missing_span_count == 0
    assert score.token_content_recall == pytest.approx(15 / 17)
    assert score.token_content_precision == pytest.approx(15 / 17)
    assert score.token_content_f1 == pytest.approx(15 / 17)
    assert score.critical["date"].recall == 1.0
    assert score.critical["money"].recall == 1.0
    assert score.critical["case_id"].recall == 1.0
    assert score.critical["citation"].recall == 1.0
    assert score.critical["article"].recall == 0.0
    assert score.legal_critical_recall == pytest.approx(5 / 7)


def test_gold_scoring_exposes_critical_identifier_corruption() -> None:
    expected = (
        "SENTENCIA TC/0001/26. Expediente TC-04-2025-0258. "
        "Artículo 53 de la Ley 137-11."
    )
    candidate = (
        "SENTENCIA TC/0007/26. Expediente TC-04-2025-025B. "
        "Artículo 58 de la Ley 137-11."
    )

    score = score_text_fidelity(
        expected_text=expected,
        candidate_text=candidate,
        required_spans=(
            "TC/0001/26",
            "TC-04-2025-0258",
            "Artículo 53",
        ),
    )

    assert score.missing_span_count == 3
    assert score.legal_critical_recall < 1.0
    assert score.critical["article"].recall == 0.0
    assert score.critical["citation"].recall == 0.0


def test_gold_scoring_is_zero_error_for_exact_text() -> None:
    text = "Artículo 12. Ley 1-24. Sentencia SCJ-SS-24-0110."
    score = score_text_fidelity(
        expected_text=text,
        candidate_text=text,
    )

    assert score.character_error_rate == pytest.approx(0.0)
    assert score.word_error_rate == pytest.approx(0.0)
    assert score.token_content_recall == pytest.approx(1.0)
    assert score.token_content_precision == pytest.approx(1.0)
    assert score.legal_critical_recall == pytest.approx(1.0)



def test_content_fidelity_is_order_insensitive_but_wer_is_not() -> None:
    expected = "Primero segundo tercero cuarto."
    reordered = "tercero cuarto primero segundo."

    score = score_text_fidelity(
        expected_text=expected,
        candidate_text=reordered,
    )

    assert score.word_error_rate > 0.0
    assert score.token_content_recall == pytest.approx(1.0)
    assert score.token_content_precision == pytest.approx(1.0)
    assert score.token_content_f1 == pytest.approx(1.0)


def test_token_order_preservation_separates_reorder_from_edit() -> None:
    expected = "Uno dos tres cuatro."

    reordered = score_text_fidelity(
        expected_text=expected,
        candidate_text="Cuatro tres dos uno.",
    )
    edited = score_text_fidelity(
        expected_text=expected,
        candidate_text="Uno dos tres cinco.",
    )

    assert reordered.token_content_recall == pytest.approx(1.0)
    assert reordered.token_content_precision == pytest.approx(1.0)
    assert reordered.token_order_preservation == pytest.approx(0.25)
    assert reordered.word_error_rate == pytest.approx(1.0)
    assert edited.token_order_preservation == pytest.approx(0.75)
    assert edited.word_error_rate == pytest.approx(0.25)


def test_critical_patterns_cover_extended_dominican_identifiers() -> None:
    text = (
        "Decreto núm. 123-24. Resolución 45-2023. Gaceta Oficial. "
        "RNC 101123456. Cédula 402-1234567-8. "
        "Matrícula 0099-2024. Parcela 123 del Distrito Catastral 4."
    )

    score = score_text_fidelity(expected_text=text, candidate_text=text)

    for category in ("decree", "resolution", "gaceta", "rnc", "cedula"):
        assert score.critical[category].expected >= 1
        assert score.critical[category].recall == 1.0
    assert score.critical["matricula"].recall == 1.0
    assert score.critical["cadastre"].recall == 1.0


def test_document_fidelity_tracks_worst_page_and_critical_loss() -> None:
    clean = TextFidelityScore(
        character_error_rate=0.01,
        word_error_rate=0.01,
        token_content_recall=1.0,
        token_content_precision=1.0,
        token_content_f1=1.0,
        token_order_preservation=1.0,
        missing_span_count=0,
        critical={"article": CriticalCategoryScore(expected=2, matched=2)},
    )
    damaged = TextFidelityScore(
        character_error_rate=0.40,
        word_error_rate=0.50,
        token_content_recall=0.90,
        token_content_precision=0.95,
        token_content_f1=0.92,
        token_order_preservation=0.80,
        missing_span_count=1,
        critical={"article": CriticalCategoryScore(expected=3, matched=2)},
    )

    document = score_document_fidelity((clean, damaged))

    assert document.page_count == 2
    assert document.worst_page_word_error_rate == pytest.approx(0.50)
    assert document.worst_page_character_error_rate == pytest.approx(0.40)
    assert document.pages_with_missing_critical == 1
    assert document.has_critical_loss is True
    assert document.aggregate_legal_critical_recall == pytest.approx(4 / 5)


def test_document_fidelity_requires_pages() -> None:
    with pytest.raises(ValueError):
        score_document_fidelity(())
