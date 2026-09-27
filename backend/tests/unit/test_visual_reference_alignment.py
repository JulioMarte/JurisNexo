from __future__ import annotations

from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)


def _reference() -> str:
    return (
        "SENTENCIA SCJ-SS-22-0514. Artículo 53 de la Ley 137-11. "
        "Fecha 31/01/2026. "
    ) * 20


def test_alignment_accepts_independent_visual_text_that_matches_native() -> None:
    text = _reference()
    assessment = assess_visual_reference_alignment(
        native_text=text,
        ocr_text=text,
        ocr_mean_confidence=96.0,
    )

    assert assessment.accepted is True
    assert assessment.rejection_reasons == ()
    assert assessment.score.word_error_rate == 0.0
    assert assessment.score.legal_critical_recall == 1.0


def test_alignment_rejects_critical_identifier_drift() -> None:
    native = _reference()
    ocr = native.replace("SCJ-SS-22-0514", "SCJ-SS-22-0519")

    assessment = assess_visual_reference_alignment(
        native_text=native,
        ocr_text=ocr,
        ocr_mean_confidence=96.0,
    )

    assert assessment.accepted is False
    assert "legal_critical_recall_too_low" in assessment.rejection_reasons


def test_alignment_rejects_low_confidence_ocr() -> None:
    text = _reference()
    assessment = assess_visual_reference_alignment(
        native_text=text,
        ocr_text=text,
        ocr_mean_confidence=50.0,
    )

    assert assessment.accepted is False
    assert "ocr_confidence_too_low" in assessment.rejection_reasons


def test_alignment_policy_is_explicit_and_configurable() -> None:
    native = _reference()
    ocr = native.replace("Artículo", "Articulo")

    strict = assess_visual_reference_alignment(
        native_text=native,
        ocr_text=ocr,
        ocr_mean_confidence=96.0,
    )
    permissive = assess_visual_reference_alignment(
        native_text=native,
        ocr_text=ocr,
        ocr_mean_confidence=96.0,
        policy=VisualReferencePolicy(
            maximum_word_error_rate=1.0,
            maximum_character_error_rate=1.0,
            minimum_token_content_recall=0.0,
            minimum_token_content_precision=0.0,
            minimum_token_order_preservation=0.0,
            minimum_legal_critical_recall=0.0,
        ),
    )

    assert permissive.accepted is True
    assert strict.ocr_mean_confidence == 96.0
