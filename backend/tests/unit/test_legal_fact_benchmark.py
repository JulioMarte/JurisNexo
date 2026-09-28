from jurisnexo.normalization.legal_fact_benchmark import (
    FACT_FIELDS,
    extract_reference_facts,
    score_legal_facts,
)


def test_extract_reference_facts_finds_legal_identifiers() -> None:
    text = (
        "Sentencia SCJ-TS-24-0001 de 2024-01-31. "
        "Se aplica la Ley 834 y el artículo 69. "
        "Condena al pago de RD$ 2,500,000.00."
    )
    facts = extract_reference_facts(text)
    assert "2024-01-31" in facts["dates"]
    assert any("Ley 834" in value for value in facts["laws"])
    assert any("artículo 69" in value for value in facts["articles"])
    assert "RD$ 2,500,000.00" in facts["amounts"]
    assert any("SCJ-TS-24-0001" in value for value in facts["case_identifiers"])


def test_score_counts_missing_and_hallucinated_values() -> None:
    expected: dict[str, tuple[str, ...]] = {field: () for field in FACT_FIELDS}
    predicted: dict[str, tuple[str, ...]] = {field: () for field in FACT_FIELDS}
    expected["laws"] = ("Ley 834", "Ley 834")
    predicted["laws"] = ("ley 834", "Ley 999")

    score = score_legal_facts(expected=expected, predicted=predicted)

    assert score.expected == 2
    assert score.predicted == 2
    assert score.matched == 1
    assert score.missed == 1
    assert score.hallucinated == 1
    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.f1 == 0.5


def test_empty_expected_does_not_reward_hallucination() -> None:
    expected: dict[str, tuple[str, ...]] = {field: () for field in FACT_FIELDS}
    predicted: dict[str, tuple[str, ...]] = {field: () for field in FACT_FIELDS}
    predicted["dates"] = ("2099-01-01",)

    score = score_legal_facts(expected=expected, predicted=predicted)

    assert score.expected == 0
    assert score.predicted == 1
    assert score.precision == 0.0
    assert score.recall == 1.0
    assert score.f1 == 0.0
