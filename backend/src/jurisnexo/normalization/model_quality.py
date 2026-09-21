from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from jurisnexo.model_providers.contracts import JsonObject, StructuredGenerationResult
from jurisnexo.normalization.judges import StructuredTextQualityJudge
from jurisnexo.normalization.provider_policy import (
    ProviderPolicy,
    enforce_provider_policy,
)


class ObservationWriter(Protocol):
    def record_observation(
        self,
        *,
        scope_id: str,
        run_item_id: str,
        artifact_id: str | None,
        observation_kind: str,
        payload: dict[str, object],
        status: str = "candidate",
        provider: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
    ) -> str: ...


class VisualQualityProvider(Protocol):
    def verify_image_text(
        self,
        *,
        image: bytes,
        media_type: str,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
    ) -> StructuredGenerationResult: ...


class CorrectionWriter(Protocol):
    def record_correction(
        self,
        *,
        scope_id: str,
        observation_id: str,
        verifier_observation_id: str | None,
        replacement_text: str,
        rationale: str | None,
        status: str = "proposed",
    ) -> str: ...


@dataclass(slots=True)
class ShadowTextQualityService:
    judge: StructuredTextQualityJudge
    writer: ObservationWriter
    provider_policy: ProviderPolicy

    def evaluate(
        self,
        *,
        scope_id: str,
        run_item_id: str,
        artifact_id: str,
        text: str,
        context: dict[str, Any],
        document_class: str,
        is_public: bool,
        redacted: bool,
    ) -> str:
        enforce_provider_policy(
            self.provider_policy,
            document_class=document_class,
            is_public=is_public,
            redacted=redacted,
        )
        decision = self.judge.judge(text, context=context)
        cost_raw = decision.get("cost_usd")
        cost = Decimal(str(cost_raw)) if isinstance(cost_raw, (int, float)) else None
        return self.writer.record_observation(
            scope_id=scope_id,
            run_item_id=run_item_id,
            artifact_id=artifact_id,
            observation_kind="text_quality_judge",
            payload={
                "pass_text": bool(decision["pass_text"]),
                "material_error_probability": float(
                    decision["material_error_probability"]
                ),
                "reasons": list(decision["reasons"]),
                "mode": "shadow",
            },
            status="candidate",
            provider=str(decision["provider"]),
            model=str(decision["model"]),
            input_tokens=_optional_int(decision.get("input_tokens")),
            output_tokens=_optional_int(decision.get("output_tokens")),
            cost_usd=cost,
        )


@dataclass(slots=True)
class SelectiveVisualVerificationService:
    provider: VisualQualityProvider
    observation_writer: ObservationWriter
    correction_writer: CorrectionWriter
    provider_policy: ProviderPolicy

    def verify(
        self,
        *,
        scope_id: str,
        run_item_id: str,
        artifact_id: str,
        source_observation_id: str,
        image: bytes,
        media_type: str,
        candidate_text: str,
        document_class: str,
        is_public: bool,
        redacted: bool,
    ) -> tuple[str, str | None]:
        enforce_provider_policy(
            self.provider_policy,
            document_class=document_class,
            is_public=is_public,
            redacted=redacted,
        )
        schema: JsonObject = {
            "type": "object",
            "properties": {
                "matches": {"type": "boolean"},
                "corrected_text": {"type": ["string", "null"]},
                "material_differences": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["matches", "corrected_text", "material_differences"],
            "additionalProperties": False,
        }
        result = self.provider.verify_image_text(
            image=image,
            media_type=media_type,
            prompt=(
                "Compare the visible legal text in the image against the candidate "
                "transcription. Do not infer text that is not visible. Return a corrected "
                "transcription only when a material visible difference exists.\n\n"
                f"Candidate:\n{candidate_text}"
            ),
            json_schema=schema,
            max_output_tokens=1200,
        )
        value = result.value
        differences_raw = value.get("material_differences", [])
        differences = (
            [str(item) for item in differences_raw]
            if isinstance(differences_raw, list)
            else []
        )
        observation_id = self.observation_writer.record_observation(
            scope_id=scope_id,
            run_item_id=run_item_id,
            artifact_id=artifact_id,
            observation_kind="visual_verification",
            payload={
                "matches": bool(value.get("matches", False)),
                "material_differences": differences,
                "source_observation_id": source_observation_id,
            },
            status="candidate",
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cost_usd=(
                Decimal(str(result.cost_usd))
                if result.cost_usd is not None
                else None
            ),
        )

        corrected = value.get("corrected_text")
        if bool(value.get("matches", False)) or not isinstance(corrected, str):
            return observation_id, None
        correction_id = self.correction_writer.record_correction(
            scope_id=scope_id,
            observation_id=source_observation_id,
            verifier_observation_id=observation_id,
            replacement_text=corrected,
            rationale="; ".join(differences) or "visual verification mismatch",
            status="proposed",
        )
        return observation_id, correction_id


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
