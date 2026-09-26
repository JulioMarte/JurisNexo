from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelProvider,
    ModelProviderError,
)
from jurisnexo.model_providers.decisions import DecisionProvider
from jurisnexo.normalization.jev_answers import (
    choice_probability,
    noul_probability,
)
from jurisnexo.normalization.jev_quality import build_text_quality_questions


@dataclass(frozen=True, slots=True)
class TextQualityDecision:
    pass_text: bool
    material_error_probability: float
    reasons: tuple[str, ...]
    provider: str
    model: str
    model_version: str | None
    response_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    total_tokens: int | None
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
            model_version=result.model_version,
            response_id=result.response_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            thinking_tokens=result.usage.thinking_tokens,
            total_tokens=result.usage.total_tokens,
            cost_usd=result.cost_usd,
        )
        return _decision_dict(decision)


@dataclass(slots=True)
class DecisionTextQualityJudge:
    """System One/JEV text-quality judge using typed probabilistic decisions."""

    provider: DecisionProvider

    def judge(self, text: str, *, context: dict[str, Any]) -> dict[str, Any]:
        record_id = "candidate"
        questions = build_text_quality_questions(
            record_ids=(record_id,),
        )
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

        acceptable = choice_probability(quality, "acceptable")
        material_error = choice_probability(quality, "material_error")
        uncertain = choice_probability(quality, "uncertain")
        critical_probability = noul_probability(critical)
        visual_probability = noul_probability(visual)

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
            model_version=result.model_version,
            response_id=result.response_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            thinking_tokens=None,
            total_tokens=result.usage.total_tokens,
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
        "model_version": decision.model_version,
        "response_id": decision.response_id,
        "input_tokens": decision.input_tokens,
        "output_tokens": decision.output_tokens,
        "thinking_tokens": decision.thinking_tokens,
        "total_tokens": decision.total_tokens,
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




def _context_json(context: dict[str, Any]) -> str:
    safe = {
        str(key): value
        for key, value in context.items()
        if value is None or isinstance(value, (bool, int, float, str))
    }
    return str(safe)
