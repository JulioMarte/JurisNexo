from __future__ import annotations

import json
import pytest

from jurisnexo.model_providers.openrouter_decisions import (
    parse_openrouter_decision_response,
)


def test_parse_openrouter_decisions_preserves_choice_noul_and_score_answers() -> None:
    payload = {
        "id": "decision-1",
        "model": "typesafe/jev-1.13",
        "answers": {
            "case_1__quality": {
                "type": "choice",
                "choice": "acceptable",
                "confidence": 0.91,
                "probabilities": {
                    "acceptable": 0.91,
                    "material_error": 0.04,
                    "uncertain": 0.05,
                },
            },
            "case_1__critical_damage": {
                "type": "noul",
                "noul": 0.08,
            },
            "case_1__risk": {
                "type": "score",
                "score": 1.3,
                "confidence": 0.80,
                "legend": {
                    "0": "low",
                    "1": "medium",
                    "2": "high",
                },
                "probabilities": {
                    "0": 0.10,
                    "1": 0.50,
                    "2": 0.40,
                },
            },
        },
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 0,
            "cost": 0.0000504,
        },
    }
    result = parse_openrouter_decision_response(
        json.dumps(payload).encode(),
        requested_model="~typesafe/jev-latest",
    )

    assert result.model == "typesafe/jev-1.13"
    assert result.response_id == "decision-1"
    quality = result.answers["case_1__quality"]
    risk = result.answers["case_1__risk"]
    assert quality["choice"] == "acceptable"
    assert quality["probabilities"]["acceptable"] == 0.91
    assert result.answers["case_1__critical_damage"]["noul"] == 0.08
    assert risk["score"] == 1.3
    assert result.usage.input_tokens == 1200
    assert result.usage.total_tokens == 1200
    assert result.cost_usd == pytest.approx(0.0000504)


def test_parse_openrouter_decisions_rejects_non_object_answers() -> None:
    payload = {
        "answers": {
            "bad": "not-an-answer-object",
        }
    }
    with pytest.raises(TypeError, match="every decision answer"):
        parse_openrouter_decision_response(
            json.dumps(payload).encode(),
            requested_model="~typesafe/jev-latest",
        )
