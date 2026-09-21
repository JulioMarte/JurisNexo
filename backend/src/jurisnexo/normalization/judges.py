from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from jurisnexo.model_providers.contracts import (
    JsonObject,
    JsonValue,
    ModelProvider,
    ModelProviderError,
)
from jurisnexo.model_providers.decisions import DecisionProvider


@dataclass(frozen=True, slots=True)
class TextQualityDecision:
    pass_text: bool
    material_error_probability: float
    reasons: tuple[str, ...]
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None


@dataclass(slots=True)
class StructuredTextQualityJudge:
    """Generative structured-output challenger, not the JEV implementation."""

    provider: ModelProvider

    def judge(self, text: str, *, context: dict[str, Any]) -> dict[str, Any]:
        schema: JsonObject = {
            "type": "object",
            "properties": {
                "pass_text": {"type": "boolean"},
                "material_error_probability": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "reasons": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pass_text", "material_error_probability", "reasons"],
            "additionalProperties": False,
        }
        prompt = (
            "Evaluate whether the candidate transcription is faithful enough for legal "
            "evidence. Do not infer missing legal text. Focus on materially wrong or "
            "missing tokens, numbers, dates, names, citations and article/law "
            "references.\n\n"
            f"Context: {context}\n\nCandidate text:\n{text}"
        )
        result = self.provider.generate_structured(
            prompt=prompt,
            json_schema=schema,
            max_output_tokens=500,
            thinking_level="none",
        )
        value = result.value
        reasons_raw = value.get("reasons", [])
        reasons = (
            tuple(str(item) for item in reasons_raw)
            if isinstance(reasons_raw, list)
            else ()
        )
        probability_raw = value.get("material_error_probability", 1.0)
        probability = float(cast(int | float, probability_raw))
        decision = TextQualityDecision(
            pass_text=bool(value.get("pass_text", False)),
            material_error_probability=probability,
            reasons=reasons,
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.cost_usd,
        )
        return _decision_dict(decision)


@dataclass(slots=True)
class DecisionTextQualityJudge:
    """System One/JEV text-quality judge using typed probabilistic decisions."""

    provider: DecisionProvider

    def judge(self, text: str, *, context: dict[str, Any]) -> dict[str, Any]:
        record_id = "candidate"
        questions: dict[str, JsonObject] = {
            f"{record_id}__transcription_quality": {
                "type": "choice",
                "instructions": (
                    'For the record with id "candidate", classify transcription '
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
            },
            f"{record_id}__legal_critical_damage": {
                "type": "noul",
                "instructions": (
                    'For the record with id "candidate", decide whether apparent '
                    "transcription damage affects legally critical tokens."
                ),
                "true_when": (
                    "Damage appears to affect names, dates, case numbers, law/article "
                    "numbers, monetary amounts, citations, holdings or dispositive text."
                ),
                "false_when": (
                    "No legally critical transcription damage is apparent."
                ),
            },
            f"{record_id}__needs_visual_review": {
                "type": "noul",
                "instructions": (
                    'For the record with id "candidate", decide whether the original '
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
            },
        }
        context_json = _context_json(context)
        result = self.provider.decide(
            state_description=(
                "One normalized legal-document text record plus deterministic context."
            ),
            records=(
                {
                    "id": record_id,
                    "record": (
                        f"Context: {context_json}\n\n"
                        f"Normalized text:\n{text}"
                    ),
                },
            ),
            questions=questions,
        )

        quality = _required_answer(
            result.answers,
            f"{record_id}__transcription_quality",
        )
        critical = _required_answer(
            result.answers,
            f"{record_id}__legal_critical_damage",
        )
        visual = _required_answer(
            result.answers,
            f"{record_id}__needs_visual_review",
        )

        acceptable = _choice_probability(quality, "acceptable")
        material_error = _choice_probability(quality, "material_error")
        uncertain = _choice_probability(quality, "uncertain")
        critical_probability = _noul_probability(critical)
        visual_probability = _noul_probability(visual)

        reasons: list[str] = []
        if material_error >= 0.5:
            reasons.append("material_error")
        if uncertain >= 0.5:
            reasons.append("uncertain")
        if critical_probability >= 0.5:
            reasons.append("legal_critical_damage")
        if visual_probability >= 0.5:
            reasons.append("needs_visual_review")

        decision = TextQualityDecision(
            pass_text=acceptable >= max(material_error, uncertain),
            material_error_probability=material_error,
            reasons=tuple(reasons),
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=result.cost_usd,
        )
        payload = _decision_dict(decision)
        payload.update(
            {
                "acceptable_probability": acceptable,
                "uncertain_probability": uncertain,
                "legal_critical_damage_probability": critical_probability,
                "needs_visual_review_probability": visual_probability,
                "decision_mode": "system_one",
            }
        )
        return payload


def _decision_dict(decision: TextQualityDecision) -> dict[str, Any]:
    return {
        "pass_text": decision.pass_text,
        "material_error_probability": decision.material_error_probability,
        "reasons": list(decision.reasons),
        "provider": decision.provider,
        "model": decision.model,
        "input_tokens": decision.input_tokens,
        "output_tokens": decision.output_tokens,
        "cost_usd": decision.cost_usd,
    }


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
    choice = cast(dict[str, JsonValue], raw_choice)
    return _probability(choice.get(option), f"choice.{option}")


def _noul_probability(answer: JsonObject) -> float:
    return _probability(answer.get("noul"), "noul")


def _probability(value: JsonValue | None, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelProviderError(f"{label} probability is not numeric")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise ModelProviderError(f"{label} probability is outside [0, 1]")
    return probability


def _context_json(context: dict[str, Any]) -> str:
    safe = {
        str(key): value
        for key, value in context.items()
        if value is None or isinstance(value, (bool, int, float, str))
    }
    return str(safe)
