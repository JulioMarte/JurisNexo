from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jurisnexo.model_providers.contracts import JsonObject, JsonValue, ModelProviderError


def build_text_quality_questions(
    *,
    record_ids: tuple[str, ...],
) -> dict[str, JsonObject]:
    questions: dict[str, JsonObject] = {}
    for record_id in record_ids:
        questions[f"{record_id}__transcription_quality"] = {
            "type": "choice",
            "instructions": (
                f'For the record with id "{record_id}", classify transcription '
                "quality only. Do not evaluate legal merits."
            ),
            "criteria": {
                "acceptable": (
                    "The text appears materially faithful and readable, without "
                    "signs of corruption affecting legal meaning."
                ),
                "material_error": (
                    "The text likely contains omissions, corruption, broken "
                    "numbering, or other damage that can change legal meaning."
                ),
                "uncertain": (
                    "The available text is insufficient to confidently choose "
                    "acceptable or material_error."
                ),
            },
        }
        questions[f"{record_id}__legal_critical_damage"] = {
            "type": "noul",
            "instructions": (
                f'For the record with id "{record_id}", decide whether apparent '
                "transcription damage affects legally critical tokens."
            ),
            "true_when": (
                "Damage appears to affect names, dates, case numbers, law/article "
                "numbers, monetary amounts, citations, holdings or dispositive text."
            ),
            "false_when": (
                "No legally critical transcription damage is apparent."
            ),
        }
        questions[f"{record_id}__needs_visual_review"] = {
            "type": "noul",
            "instructions": (
                f'For the record with id "{record_id}", decide whether the original '
                "page image should be checked before accepting the text."
            ),
            "true_when": (
                "Material uncertainty or suspicious corruption cannot be safely "
                "resolved from the normalized text alone."
            ),
            "false_when": (
                "The normalized text is sufficiently clear that visual escalation "
                "is not warranted."
            ),
        }
    return questions


def parse_text_quality_probabilities(
    answers: dict[str, JsonObject],
    *,
    record_id: str,
) -> TextQualityProbabilities:
    quality = _required_answer(
        answers,
        f"{record_id}__transcription_quality",
    )
    critical = _required_answer(
        answers,
        f"{record_id}__legal_critical_damage",
    )
    visual = _required_answer(
        answers,
        f"{record_id}__needs_visual_review",
    )
    return TextQualityProbabilities(
        acceptable=_choice_probability(quality, "acceptable"),
        material_error=_choice_probability(quality, "material_error"),
        uncertain=_choice_probability(quality, "uncertain"),
        legal_critical_damage=_noul_probability(critical),
        needs_visual_review=_noul_probability(visual),
    )


def _required_answer(
    answers: dict[str, JsonObject],
    key: str,
) -> JsonObject:
    answer = answers.get(key)
    if answer is None:
        raise ModelProviderError(f"decision response omitted {key}")
    return answer


def _choice_probability(answer: JsonObject, option: str) -> float:
    raw_choice = answer.get("choice")
    if not isinstance(raw_choice, dict):
        raise ModelProviderError("choice answer is not an object")
    choice = dict(raw_choice)
    return _probability(choice.get(option), f"choice.{option}")


def _noul_probability(answer: JsonObject) -> float:
    return _probability(answer.get("noul"), "noul")


def _probability(value: JsonValue | object | None, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelProviderError(f"{label} probability is not numeric")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise ModelProviderError(f"{label} probability is outside [0, 1]")
    return probability


RoutingAction = Literal[
    "accept",
    "sentinel",
    "deepseek_review",
    "visual_review",
    "human_review",
]


@dataclass(frozen=True, slots=True)
class TextQualityProbabilities:
    acceptable: float
    material_error: float
    uncertain: float
    legal_critical_damage: float
    needs_visual_review: float


@dataclass(frozen=True, slots=True)
class JevRoutingPolicy:
    """Threshold policy calibrated separately from the JEV provider.

    Defaults are deliberately shadow-safe: they support deterministic tests and
    routing experiments but are not a production promotion claim. Promotion
    requires measured calibration/holdout evidence.
    """

    auto_accept_min_acceptable: float = 0.98
    sentinel_min_acceptable: float = 0.90
    deepseek_min_material_error: float = 0.20
    visual_min_probability: float = 0.35
    human_min_uncertain: float = 0.60
    critical_visual_multiplier: float = 0.75

    def __post_init__(self) -> None:
        values = (
            self.auto_accept_min_acceptable,
            self.sentinel_min_acceptable,
            self.deepseek_min_material_error,
            self.visual_min_probability,
            self.human_min_uncertain,
            self.critical_visual_multiplier,
        )
        if any(not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("JEV routing thresholds must stay within [0, 1]")
        if self.sentinel_min_acceptable > self.auto_accept_min_acceptable:
            raise ValueError(
                "sentinel_min_acceptable cannot exceed auto_accept_min_acceptable"
            )

    def route(self, probabilities: TextQualityProbabilities) -> RoutingAction:
        if probabilities.uncertain >= self.human_min_uncertain:
            return "human_review"

        critical_visual_threshold = (
            self.visual_min_probability * self.critical_visual_multiplier
            if probabilities.legal_critical_damage >= 0.5
            else self.visual_min_probability
        )
        if probabilities.needs_visual_review >= critical_visual_threshold:
            return "visual_review"

        if probabilities.material_error >= self.deepseek_min_material_error:
            return "deepseek_review"

        if probabilities.acceptable >= self.auto_accept_min_acceptable:
            return "accept"

        if probabilities.acceptable >= self.sentinel_min_acceptable:
            return "sentinel"

        return "deepseek_review"
