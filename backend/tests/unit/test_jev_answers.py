from __future__ import annotations

import pytest

from jurisnexo.model_providers.contracts import JsonObject, ModelProviderError
from jurisnexo.normalization.jev_answers import (
    choice_confidence,
    choice_probability,
    choice_selected,
    noul_probability,
    score_probabilities,
    score_value,
)


def test_official_choice_answer_preserves_selection_confidence_and_distribution() -> None:
    answer: JsonObject = {
        "type": "choice",
        "choice": "acceptable",
        "confidence": 0.91,
        "probabilities": {
            "acceptable": 0.91,
            "material_error": 0.04,
            "uncertain": 0.05,
        },
    }

    assert choice_selected(answer) == "acceptable"
    assert choice_confidence(answer) == pytest.approx(0.91)
    assert choice_probability(answer, "acceptable") == pytest.approx(0.91)


def test_official_noul_answer_is_yes_probability() -> None:
    answer: JsonObject = {
        "type": "noul",
        "noul": 0.18,
    }
    assert noul_probability(answer) == pytest.approx(0.18)


def test_official_score_answer_preserves_expected_score_and_distribution() -> None:
    answer: JsonObject = {
        "type": "score",
        "score": 1.4,
        "confidence": 0.72,
        "legend": {
            "0": "low",
            "1": "medium",
            "2": "high",
        },
        "probabilities": {
            "0": 0.10,
            "1": 0.40,
            "2": 0.50,
        },
    }

    assert score_value(answer) == pytest.approx(1.4)
    assert score_probabilities(answer)["2"] == pytest.approx(0.50)


def test_choice_parser_rejects_missing_probability_distribution() -> None:
    with pytest.raises(ModelProviderError, match="probability distribution"):
        choice_probability(
            {
                "type": "choice",
                "choice": "acceptable",
                "confidence": 0.9,
            },
            "acceptable",
        )
