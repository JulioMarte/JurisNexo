from __future__ import annotations

import json
from typing import cast

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
                "choice": {
                    "acceptable": 0.91,
                    "material_error": 0.04,
                    "uncertain": 0.05,
                }
            },
            "case_1__critical_damage": {"noul": 0.08},
            "case_1__risk": {
                "score": {
                    "value": 1,
                    "probabilities": [0.75, 0.2, 0.05],
                }
            },
        },
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 0,
            "total_tokens": 1200,
            "cost": 0.0000504,
        },
    }
    result = parse_openrouter_decision_response(
        json.dumps(payload).encode(),
        requested_model="~typesafe/jev-latest",
    )

    assert result.model == "typesafe/jev-1.13"
    assert result.response_id == "decision-1"
    quality = cast(
        dict[str, float],
        result.answers["case_1__quality"]["choice"],
    )
    risk = cast(
        dict[str, object],
        result.answers["case_1__risk"]["score"],
    )
    assert quality["acceptable"] == 0.91
    assert result.answers["case_1__critical_damage"]["noul"] == 0.08
    assert risk["value"] == 1
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
