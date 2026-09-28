from __future__ import annotations

from legal_fact_gold_v1 import extract_gold


def test_oracle_extracts_explicit_values_without_deduplicating_across_fields() -> None:
    result = extract_gold(
        "La sentencia SCJ-SS-22-1191 aplica el artículo 5 de la Ley 834. "
        "Se condena al pago de RD$ 25,000.00. SCJ-SS-22-1191."
    )
    assert result["articles"] == ["artículo 5"]
    assert result["laws"] == ["Ley 834"]
    assert result["money"] == ["RD$ 25,000.00"]
    assert result["citations"] == ["SCJ-SS-22-1191"]
    assert result["case_ids"] == [
        "sentencia SCJ-SS-22-1191",
        "SCJ-SS-22-1191",
    ]


def test_oracle_keeps_absent_categories_empty() -> None:
    result = extract_gold("Texto sin identificadores ni referencias legales.")
    assert all(values == [] for values in result.values())
