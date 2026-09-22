from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.decisions import DecisionResult, DecisionUsage
from jurisnexo.normalization.decision_batching import (
    DecisionBatchPolicy,
    DecisionRecord,
)
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator


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
        questions: dict[str, dict[str, object]],
    ) -> DecisionResult:
        del state_description
        self.calls += 1
        answers: dict[str, dict[str, object]] = {}
        for record in records:
            record_id = record["id"]
            answers[f"{record_id}__transcription_quality"] = {
                "choice": {
                    "acceptable": 0.9,
                    "material_error": 0.05,
                    "uncertain": 0.05,
                }
            }
            answers[f"{record_id}__legal_critical_damage"] = {
                "noul": 0.1,
            }
            answers[f"{record_id}__needs_visual_review"] = {
                "noul": 0.2,
            }
        assert set(questions) == set(answers)
        return DecisionResult(
            answers=answers,
            provider="fake",
            model="fake-jev",
            model_version="fake-jev",
            response_id=f"call-{self.calls}",
            usage=DecisionUsage(
                input_tokens=100 * len(records),
                output_tokens=0,
                total_tokens=100 * len(records),
            ),
            cost_usd=0.0001 * len(records),
        )


def test_batched_evaluator_returns_probabilities_and_telemetry() -> None:
    provider = _FakeDecisionProvider()
    evaluator = JevBatchQualityEvaluator(
        provider=provider,
        policy=DecisionBatchPolicy(
            target_total_tokens=7000,
            reserved_instruction_tokens=1000,
            max_records_per_batch=2,
        ),
    )
    records = tuple(
        DecisionRecord(
            record_id=f"r{index}",
            text="Texto jurídico normalizado. " * 20,
        )
        for index in range(5)
    )

    result = evaluator.evaluate(
        records=records,
        state_description="Quality routing.",
    )

    assert provider.calls == 3
    assert len(result.records) == 5
    assert len(result.batches) == 3
    assert sum(batch.record_count for batch in result.batches) == 5
    assert result.records[0].probabilities.acceptable == 0.9
    assert result.records[0].probabilities.needs_visual_review == 0.2
    assert sum(batch.cost_usd or 0.0 for batch in result.batches) == 0.0005
