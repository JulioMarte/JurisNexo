from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.decisions import (
    DecisionQuestion,
    DecisionResult,
    DecisionUsage,
)
from jurisnexo.normalization.decision_batching import DecisionBatchPolicy
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.model_quality import (
    BatchedShadowTextQualityService,
    ShadowQualityCandidate,
)
from jurisnexo.normalization.provider_policy import ProviderPolicy


@dataclass
class _FakeDecisionProvider:
    calls: int = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-jev"

    def decide(
        self,
        *,
        state_description: str,
        records: tuple[dict[str, str], ...],
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResult:
        del state_description
        self.calls += 1
        answers: dict[str, JsonObject] = {}
        for record in records:
            record_id = record["id"]
            answers[f"{record_id}__transcription_quality"] = {
                "type": "choice",
                "choice": "acceptable",
                "confidence": 0.96,
                "probabilities": {
                    "acceptable": 0.96,
                    "material_error": 0.02,
                    "uncertain": 0.02,
                },
            }
            answers[f"{record_id}__legal_critical_damage"] = {
                "type": "noul",
                "noul": 0.05,
            }
            answers[f"{record_id}__needs_visual_review"] = {
                "type": "noul",
                "noul": 0.05,
            }
        assert set(questions) == set(answers)
        return DecisionResult(
            answers=answers,
            provider="fake",
            model="fake-jev",
            model_version="fake-jev-v1",
            response_id=f"response-{self.calls}",
            usage=DecisionUsage(
                input_tokens=100 * len(records),
                output_tokens=0,
                total_tokens=100 * len(records),
            ),
            cost_usd=0.0001 * len(records),
        )


@dataclass
class _Writer:
    model_calls: list[dict[str, object]] = field(default_factory=list)
    observations: list[dict[str, object]] = field(default_factory=list)

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
    ) -> str:
        call_id = f"call-{len(self.model_calls)}"
        self.model_calls.append(
            {
                "id": call_id,
                "scope_id": scope_id,
                "run_id": run_id,
                "purpose": purpose,
                "provider": provider,
                "model": model,
                "model_version": model_version,
                "response_id": response_id,
                "estimated_input_tokens": estimated_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "metadata": metadata or {},
            }
        )
        return call_id

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
    ) -> str:
        observation_id = f"observation-{len(self.observations)}"
        self.observations.append(
            {
                "id": observation_id,
                "scope_id": scope_id,
                "run_item_id": run_item_id,
                "artifact_id": artifact_id or "",
                "observation_kind": observation_kind,
                "payload": payload,
                "status": status,
                "model_call_id": model_call_id or "",
            }
        )
        return observation_id


def test_batched_shadow_service_accounts_once_per_provider_call() -> None:
    provider = _FakeDecisionProvider()
    writer = _Writer()
    service = BatchedShadowTextQualityService(
        evaluator=JevBatchQualityEvaluator(
            provider=provider,
            policy=DecisionBatchPolicy(
                target_total_tokens=7000,
                reserved_instruction_tokens=1000,
                max_records_per_batch=2,
            ),
        ),
        writer=writer,
        provider_policy=ProviderPolicy(provider="fake"),
    )
    candidates = tuple(
        ShadowQualityCandidate(
            run_item_id=f"item-{index}",
            artifact_id=f"artifact-{index}",
            text="Texto jurídico normalizado. " * 20,
            context={"source": "SCJ", "page": index},
            document_class="public_judgment",
            is_public=True,
            redacted=False,
        )
        for index in range(5)
    )

    observation_ids = service.evaluate_many(
        scope_id="scope",
        run_id="run",
        candidates=candidates,
    )

    assert provider.calls == 3
    assert len(writer.model_calls) == 3
    assert len(writer.observations) == 5
    assert len(observation_ids) == 5
    observed_cost = 0.0
    for call in writer.model_calls:
        raw_cost = call["cost_usd"]
        if isinstance(raw_cost, Decimal):
            observed_cost += float(raw_cost)
    assert observed_cost == 0.0005
    assert {
        observation["model_call_id"]
        for observation in writer.observations
    } == {"call-0", "call-1", "call-2"}
    payloads = tuple(
        cast(dict[str, object], observation["payload"])
        for observation in writer.observations
    )
    assert all(payload["mode"] == "shadow" for payload in payloads)
    assert all(
        payload["recommended_action"] == "sentinel"
        for payload in payloads
    )
