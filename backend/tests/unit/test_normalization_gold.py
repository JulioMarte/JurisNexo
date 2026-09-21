from __future__ import annotations

import pytest

from jurisnexo.normalization.gold import score_text_fidelity


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
    assert score.critical["date"].recall == 1.0
    assert score.critical["money"].recall == 1.0
    assert score.critical["case_id"].recall == 1.0
    assert score.legal_critical_recall >= 0.75


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
    assert score.legal_critical_recall == pytest.approx(1.0)
