from __future__ import annotations

from typing import cast

from jurisnexo.model_providers.contracts import (
    JsonObject,
    JsonValue,
    ModelProviderError,
)


def choice_probabilities(answer: JsonObject) -> dict[str, float]:
    answer_type = answer.get("type")
    if answer_type is not None and answer_type != "choice":
        raise ModelProviderError("expected a choice answer")

    raw = answer.get("probabilities")
    if not isinstance(raw, dict):
        # Temporary compatibility for early OpenRouter lab fixtures that nested
        # the distribution under "choice". Live TypeSafe/OpenRouter responses
        # use the official System One ChoiceAnswer shape.
        legacy = answer.get("choice")
        if isinstance(legacy, dict):
            raw = legacy
        else:
            raise ModelProviderError(
                "choice answer does not contain a probability distribution"
            )

    typed = cast(dict[object, object], raw)
    probabilities: dict[str, float] = {}
    for key, value in typed.items():
        probabilities[str(key)] = probability(
            cast(JsonValue | object | None, value),
            f"choice.probabilities.{key}",
        )
    if not probabilities:
        raise ModelProviderError("choice probability distribution is empty")
    return probabilities


def choice_probability(answer: JsonObject, option: str) -> float:
    probabilities = choice_probabilities(answer)
    try:
        return probabilities[option]
    except KeyError as exc:
        raise ModelProviderError(
            f"choice response omitted expected option {option!r}"
        ) from exc


def choice_selected(answer: JsonObject) -> str | None:
    raw = answer.get("choice")
    return raw if isinstance(raw, str) else None


def choice_confidence(answer: JsonObject) -> float | None:
    raw = answer.get("confidence")
    if raw is None:
        return None
    return probability(raw, "choice.confidence")


def noul_probability(answer: JsonObject) -> float:
    answer_type = answer.get("type")
    if answer_type is not None and answer_type != "noul":
        raise ModelProviderError("expected a noul answer")
    return probability(answer.get("noul"), "noul")


def score_value(answer: JsonObject) -> float:
    answer_type = answer.get("type")
    if answer_type is not None and answer_type != "score":
        raise ModelProviderError("expected a score answer")
    raw = answer.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ModelProviderError("score answer is not numeric")
    return float(raw)


def score_probabilities(answer: JsonObject) -> dict[str, float]:
    raw = answer.get("probabilities")
    if not isinstance(raw, dict):
        raise ModelProviderError(
            "score answer does not contain a probability distribution"
        )
    typed = cast(dict[object, object], raw)
    return {
        str(key): probability(
            cast(JsonValue | object | None, value),
            f"score.probabilities.{key}",
        )
        for key, value in typed.items()
    }


def probability(value: JsonValue | object | None, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelProviderError(f"{label} probability is not numeric")
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ModelProviderError(f"{label} probability is outside [0, 1]")
    return result
