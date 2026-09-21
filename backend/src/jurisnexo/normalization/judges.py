from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from jurisnexo.model_providers.contracts import JsonObject, ModelProvider


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
    """Atomic text-quality judge suitable for JEV shadow evaluation."""

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
            "Evaluate whether the candidate transcription is faithful enough for legal evidence. "
            "Do not infer missing legal text. Focus on materially wrong or missing tokens, numbers, "
            "dates, names, citations and article/law references.\n\n"
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
        reasons = tuple(str(item) for item in reasons_raw) if isinstance(reasons_raw, list) else ()
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
