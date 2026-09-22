from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from jurisnexo.model_providers.contracts import JsonObject, StructuredGenerationResult
from jurisnexo.normalization.contracts import TextQualityJudge
from jurisnexo.normalization.decision_batching import DecisionRecord
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.jev_quality import JevRoutingPolicy
from jurisnexo.normalization.provider_policy import (
    ProviderPolicy,
    enforce_provider_policy,
)


class ModelCallWriter(Protocol):
    def record_model_call(
        self,
        *,
        scope_id: str,
        run_id: str,
        purpose: str,
        provider: str,
        model: str,
        model_version: str | None,
        response_id: str | None,
        estimated_input_tokens: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        cost_usd: Decimal | None,
        latency_ms: int | None,
        metadata: dict[str, object] | None = None,
    ) -> str: ...


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
        model_call_id: str | None = None,
    ) -> str: ...


class QualityEvidenceWriter(ModelCallWriter, ObservationWriter, Protocol):
    pass


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


@dataclass(frozen=True, slots=True)
class ShadowQualityCandidate:
    run_item_id: str
    artifact_id: str
    text: str
    context: dict[str, Any]
    document_class: str
    is_public: bool
    redacted: bool


@dataclass(slots=True)
class ShadowTextQualityService:
    """Single-record compatibility path for generative or decision judges."""

    judge: TextQualityJudge
    writer: QualityEvidenceWriter
    provider_policy: ProviderPolicy

    def evaluate(
        self,
        *,
        scope_id: str,
        run_id: str,
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
        started = time.perf_counter()
        decision = self.judge.judge(text, context=context)
        latency_ms = int((time.perf_counter() - started) * 1000)

        cost = _decimal_or_none(decision.get("cost_usd"))
        model_call_id = self.writer.record_model_call(
            scope_id=scope_id,
            run_id=run_id,
            purpose="text_quality_judge",
            provider=str(decision["provider"]),
            model=str(decision["model"]),
            model_version=_optional_str(decision.get("model_version")),
            response_id=_optional_str(decision.get("response_id")),
            estimated_input_tokens=None,
            input_tokens=_optional_int(decision.get("input_tokens")),
            output_tokens=_optional_int(decision.get("output_tokens")),
            total_tokens=_optional_int(decision.get("total_tokens")),
            cost_usd=cost,
            latency_ms=latency_ms,
            metadata={"mode": "single"},
        )
        payload = _single_decision_payload(decision)
        return self.writer.record_observation(
            scope_id=scope_id,
            run_item_id=run_item_id,
            artifact_id=artifact_id,
            observation_kind="text_quality_judge",
            payload=payload,
            status="candidate",
            model_call_id=model_call_id,
        )


@dataclass(slots=True)
class BatchedShadowTextQualityService:
    """System One/JEV shadow evaluation using safe context-window batching."""

    evaluator: JevBatchQualityEvaluator
    writer: QualityEvidenceWriter
    provider_policy: ProviderPolicy
    routing_policy: JevRoutingPolicy = JevRoutingPolicy()

    def evaluate_many(
        self,
        *,
        scope_id: str,
        run_id: str,
        candidates: tuple[ShadowQualityCandidate, ...],
    ) -> tuple[str, ...]:
        if not candidates:
            return ()

        by_record_id: dict[str, ShadowQualityCandidate] = {}
        records: list[DecisionRecord] = []
        for candidate in candidates:
            enforce_provider_policy(
                self.provider_policy,
                document_class=candidate.document_class,
                is_public=candidate.is_public,
                redacted=candidate.redacted,
            )
            if candidate.run_item_id in by_record_id:
                raise ValueError(
                    f"duplicate shadow-quality run item {candidate.run_item_id}"
                )
            by_record_id[candidate.run_item_id] = candidate
            records.append(
                DecisionRecord(
                    record_id=candidate.run_item_id,
                    text=candidate.text,
                    metadata=_scalar_json(candidate.context),
                )
            )

        result = self.evaluator.evaluate(
            records=tuple(records),
            state_description=(
                "Records are normalized legal-document text plus deterministic "
                "context. Judge transcription quality only. Do not decide legal merits."
            ),
        )

        model_calls: dict[int, str] = {}
        for batch in result.batches:
            model_calls[batch.batch_index] = self.writer.record_model_call(
                scope_id=scope_id,
                run_id=run_id,
                purpose="text_quality_judge",
                provider=batch.provider,
                model=batch.model,
                model_version=batch.model_version,
                response_id=batch.response_id,
                estimated_input_tokens=batch.estimated_total_tokens,
                input_tokens=batch.input_tokens,
                output_tokens=batch.output_tokens,
                total_tokens=batch.total_tokens,
                cost_usd=(
                    Decimal(str(batch.cost_usd))
                    if batch.cost_usd is not None
                    else None
                ),
                latency_ms=batch.latency_ms,
                metadata={
                    "mode": "system_one_batch",
                    "record_ids": list(batch.record_ids),
                },
            )

        observation_ids: list[str] = []
        for evaluation in result.records:
            candidate = by_record_id[evaluation.record_id]
            probabilities = evaluation.probabilities
            recommendation = self.routing_policy.recommend(probabilities)
            observation_ids.append(
                self.writer.record_observation(
                    scope_id=scope_id,
                    run_item_id=candidate.run_item_id,
                    artifact_id=candidate.artifact_id,
                    observation_kind="text_quality_judge",
                    payload={
                        "acceptable_probability": probabilities.acceptable,
                        "material_error_probability": probabilities.material_error,
                        "uncertain_probability": probabilities.uncertain,
                        "legal_critical_damage_probability": (
                            probabilities.legal_critical_damage
                        ),
                        "needs_visual_review_probability": (
                            probabilities.needs_visual_review
                        ),
                        "recommended_action": recommendation,
                        "mode": "shadow",
                    },
                    status="candidate",
                    model_call_id=model_calls[evaluation.batch_index],
                )
            )
        return tuple(observation_ids)


@dataclass(slots=True)
class SelectiveVisualVerificationService:
    provider: VisualQualityProvider
    observation_writer: QualityEvidenceWriter
    correction_writer: CorrectionWriter
    provider_policy: ProviderPolicy

    def verify(
        self,
        *,
        scope_id: str,
        run_id: str,
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
        started = time.perf_counter()
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
        latency_ms = int((time.perf_counter() - started) * 1000)

        model_call_id = self.observation_writer.record_model_call(
            scope_id=scope_id,
            run_id=run_id,
            purpose="visual_verification",
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            response_id=result.response_id,
            estimated_input_tokens=None,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            cost_usd=(
                Decimal(str(result.cost_usd))
                if result.cost_usd is not None
                else None
            ),
            latency_ms=latency_ms,
            metadata={
                "mode": "selective_visual",
                "provider_metadata": result.provider_metadata or {},
            },
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
            model_call_id=model_call_id,
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


def _single_decision_payload(decision: dict[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {
        "pass_text": bool(decision["pass_text"]),
        "material_error_probability": float(
            decision["material_error_probability"]
        ),
        "reasons": list(decision["reasons"]),
        "mode": "shadow",
    }
    for key in (
        "acceptable_probability",
        "uncertain_probability",
        "legal_critical_damage_probability",
        "needs_visual_review_probability",
    ):
        value = decision.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            payload[key] = float(value)
    return payload


def _scalar_json(context: dict[str, Any]) -> JsonObject:
    return {
        str(key): value
        for key, value in context.items()
        if value is None or isinstance(value, (bool, int, float, str))
    }


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _decimal_or_none(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))
