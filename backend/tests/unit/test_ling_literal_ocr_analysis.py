from __future__ import annotations

import pytest

from jurisnexo.normalization.ling_literal_ocr_analysis import (
    ANOMALY_EMPTY,
    ANOMALY_FENCE,
    ANOMALY_ILEGIBLE,
    ANOMALY_NON_TRANSCRIPTION,
    ANOMALY_REPEATED_CHARACTER,
    ANOMALY_WRAPPER,
    CHANGE_ACCENT,
    CHANGE_CASE,
    CHANGE_DIGITS,
    CHANGE_EXACT,
    CHANGE_PUNCTUATION,
    CHANGE_SUBSTANTIVE,
    CHANGE_WHITESPACE,
    PageEvidence,
    analyze_evidence,
    classify_change,
    detect_anomalies,
    has_repetition_loop,
    legal_span_disagreements,
    legal_spans,
    pass_evidence_from_mapping,
    substantive_similarity,
)

pytestmark = [pytest.mark.unit]

EXPECTED_MODEL = "inclusionai/ling-3.0-flash-vl"
EXPECTED_PROVIDER = "NovitaAI"


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("texto", "texto", CHANGE_EXACT),
        ("a  b", "a b", CHANGE_WHITESPACE),
        ("Hola", "hola", CHANGE_CASE),
        ("acción", "accion", CHANGE_ACCENT),
        ("a, b", "a b", CHANGE_PUNCTUATION),
        ("artículo 5", "artículo 6", CHANGE_DIGITS),
        ("resolución distinta", "otra cosa", CHANGE_SUBSTANTIVE),
    ],
)
def test_classify_change_taxonomy(first: str, second: str, expected: str) -> None:
    assert classify_change(first, second) == expected


def test_legal_spans_extracts_expected_categories() -> None:
    text = (
        "Sentencia SCJ-SS-22-0516 del 12/03/2022, artículo 5 de la Ley 35, "
        "por RD$ 100,000.00 en el año 2021."
    )

    spans = legal_spans(text)

    assert spans["identifier"] == frozenset({"SCJ-SS-22-0516"})
    assert spans["year"] == frozenset({"2021", "2022"})
    assert spans["date"] == frozenset({"12/03/2022"})
    assert spans["money"] == frozenset({"RD$ 100,000.00"})
    assert spans["reference"] == frozenset({"artículo 5", "ley 35"})


def test_legal_span_disagreements_reports_both_sides() -> None:
    first = "Sentencia SCJ-SS-22-0516 del año 2008."
    second = "Sentencia SCJ-SS-22-0517 del año 2009."

    disagreements = legal_span_disagreements(first, second)

    assert disagreements["identifier"] == {
        "first_only": ["SCJ-SS-22-0516"],
        "second_only": ["SCJ-SS-22-0517"],
    }
    assert disagreements["year"] == {
        "first_only": ["2008"],
        "second_only": ["2009"],
    }
    assert "date" not in disagreements


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("   \n  ", ANOMALY_EMPTY),
        ("---BEGIN OCR---\ntexto\n---END OCR---", ANOMALY_WRAPPER),
        ("```\ntexto\n```", ANOMALY_FENCE),
        ("texto [ilegible] texto", ANOMALY_ILEGIBLE),
        ("I cannot transcribe this page.", ANOMALY_NON_TRANSCRIPTION),
        ("a" * 60, ANOMALY_REPEATED_CHARACTER),
    ],
)
def test_detect_anomalies_positive_cases(text: str, expected: str) -> None:
    assert expected in detect_anomalies(text)


def test_detect_anomalies_does_not_flag_legal_prose() -> None:
    legal = (
        "De lo anterior no es posible su aplicación, pues aquí está la cuestión.\n"
        "El recurso de apelación no procede contra esta decisión."
    )

    assert detect_anomalies(legal) == frozenset()


def test_repetition_loop_requires_consecutive_repeats() -> None:
    consecutive = "\n".join(["Rechaza."] * 6)
    scattered = "\n".join(["Rechaza." if i % 3 == 0 else f"párrafo {i}" for i in range(24)])

    assert has_repetition_loop(consecutive) is True
    assert has_repetition_loop(scattered) is False


def test_substantive_similarity_is_identity_for_equal_text() -> None:
    assert substantive_similarity("mismo texto", "mismo texto") == 1.0


def _pass(transcription: str, *, cost: float, tokens: int, pixel: str | None) -> dict[str, object]:
    return {
        "transcription": transcription,
        "tokens_completion": tokens,
        "total_cost_usd": cost,
        "latency_seconds_client": 1.0,
        "returned_model": EXPECTED_MODEL,
        "returned_provider": "Novita",
        "render_pixel_sha256": pixel,
    }


def test_analyze_evidence_aggregates_routing_signals() -> None:
    pages = [
        PageEvidence(
            document_id="doc-b",
            page_index=1,
            source_classification="misaligned",
            first=pass_evidence_from_mapping(
                _pass(
                    "Sentencia SCI-SS-22-0516 del año 2008, primera parte",
                    cost=0.01,
                    tokens=100,
                    pixel="p" * 8,
                )
            ),
            second=pass_evidence_from_mapping(
                _pass(
                    "Sentencia SCJ-SS-22-0517 del año 2009, segunda parte",
                    cost=0.02,
                    tokens=110,
                    pixel="p" * 8,
                )
            ),
        ),
        PageEvidence(
            document_id="doc-a",
            page_index=0,
            source_classification="no_native_text",
            first=pass_evidence_from_mapping(
                _pass("texto idéntico", cost=0.03, tokens=120, pixel=None)
            ),
            second=pass_evidence_from_mapping(
                _pass("texto  idéntico", cost=0.04, tokens=130, pixel=None)
            ),
        ),
        PageEvidence(
            document_id="doc-a",
            page_index=1,
            source_classification="misaligned",
            first=pass_evidence_from_mapping(
                _pass("   ", cost=0.05, tokens=140, pixel="q" * 8)
            ),
            second=None,
        ),
    ]

    report = analyze_evidence(
        pages,
        expected_model=EXPECTED_MODEL,
        expected_provider=EXPECTED_PROVIDER,
    )

    assert report["page_count"] == 3
    assert report["missing_second_pass"] == 1
    assert report["change_taxonomy"][CHANGE_EXACT] == 0
    assert report["change_taxonomy"][CHANGE_SUBSTANTIVE] == 1
    assert report["change_taxonomy"][CHANGE_WHITESPACE] == 1
    assert report["substantive"]["count"] == 1
    assert report["anomalies"]["pass1"][ANOMALY_EMPTY] == 1
    assert len(report["legal_disagreements"]) == 2
    assert {row["category"] for row in report["legal_disagreements"]} == {"identifier", "year"}
    assert report["runtime"]["cost_total_usd"] == pytest.approx(0.15)
    assert report["runtime"]["cost_pass1_usd"] == pytest.approx(0.09)
    assert report["runtime"]["cost_pass2_usd"] == pytest.approx(0.06)
    assert report["runtime"]["render_pixel_verified"] == 1
    assert report["runtime"]["render_legacy_unverified"] == 1
    assert [doc["document_id"] for doc in report["documents"]] == ["doc-a", "doc-b"]


def test_pass_evidence_from_mapping_is_defensive() -> None:
    record = pass_evidence_from_mapping({"transcription": None, "tokens_completion": "x"})

    assert record.transcription == ""
    assert record.completion_tokens == 0
    assert record.cost_usd == 0.0
    assert record.render_pixel_sha256 is None
