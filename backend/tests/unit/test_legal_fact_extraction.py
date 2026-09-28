from __future__ import annotations

from jurisnexo.normalization.legal_fact_extraction import (
    LEGAL_FACT_FIELDS,
    build_legal_fact_prompt,
    empty_legal_fact_payload,
    score_legal_fact_extraction,
    validate_legal_fact_payload,
)


def _payload(**overrides: list[str]) -> dict[str, list[str]]:
    value = empty_legal_fact_payload()
    value.update(overrides)
    return value


def test_score_accepts_case_and_whitespace_only_differences() -> None:
    score = score_legal_fact_extraction(
        expected=_payload(articles=["Artículo 5"], laws=["Ley 834"]),
        predicted=_payload(articles=[" artículo   5 "], laws=["LEY 834"]),
    )
    assert score.exact_page is True
    assert score.precision == 1.0
    assert score.recall == 1.0


def test_score_separates_missing_values_from_hallucinated_values() -> None:
    score = score_legal_fact_extraction(
        expected=_payload(articles=["Artículo 5"], laws=["Ley 834"]),
        predicted=_payload(articles=["Artículo 7"], laws=[]),
    )
    assert score.false_positive == 1
    assert score.false_negative == 2
    assert score.fields["articles"].false_positive == 1
    assert score.fields["articles"].false_negative == 1
    assert score.fields["laws"].false_negative == 1


def test_duplicate_predictions_do_not_inflate_precision_or_recall() -> None:
    score = score_legal_fact_extraction(
        expected=_payload(case_ids=["SCJ-SS-22-1191"]),
        predicted=_payload(case_ids=["SCJ-SS-22-1191", "SCJ-SS-22-1191"]),
    )
    assert score.exact_page is True
    assert score.predicted == 1


def test_payload_rejects_missing_schema_fields() -> None:
    value: dict[str, object] = {
        field: list[str]() for field in LEGAL_FACT_FIELDS[:-1]
    }
    try:
        validate_legal_fact_payload(value)
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing field must be rejected")


def test_prompt_forbids_inference_and_contains_source_text() -> None:
    prompt = build_legal_fact_prompt("Ley 834, artículo 5")
    assert "Do not infer" in prompt
    assert "Ley 834, artículo 5" in prompt
