from __future__ import annotations

import pytest

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.normalization.decision_batching import (
    DecisionBatchPolicy,
    DecisionRecord,
    estimate_legal_text_tokens,
    plan_decision_batches,
    plan_record_scoped_decision_batches,
)


def _questions() -> dict[str, JsonObject]:
    return {
        "quality": {
            "type": "choice",
            "criteria": {
                "acceptable": "usable",
                "material_error": "damaged",
                "uncertain": "uncertain",
            },
        }
    }


def test_batch_planner_keeps_headroom_below_32k_context() -> None:
    records = tuple(
        DecisionRecord(
            record_id=f"r{index}",
            text=("Artículo 53 de la Ley 137-11. " * 180),
        )
        for index in range(8)
    )
    policy = DecisionBatchPolicy(
        max_context_tokens=32_000,
        target_total_tokens=12_000,
        reserved_instruction_tokens=2_000,
        max_records_per_batch=20,
    )

    batches = plan_decision_batches(
        records,
        questions=_questions(),
        state_description="Dominican legal-text quality routing.",
        policy=policy,
    )

    assert len(batches) >= 2
    assert all(
        batch.estimated_total_tokens < policy.max_context_tokens
        for batch in batches
    )
    assert all(
        batch.estimated_total_tokens <= policy.target_total_tokens
        for batch in batches
    )
    flattened = tuple(
        record.record_id
        for batch in batches
        for record in batch.records
    )
    assert flattened == tuple(record.record_id for record in records)


def test_batch_planner_never_silently_truncates_oversized_record() -> None:
    record = DecisionRecord(
        record_id="oversized",
        text="x" * 100_000,
    )
    with pytest.raises(ValueError, match="exceeds the safe JEV batch budget"):
        plan_decision_batches(
            (record,),
            questions=_questions(),
            state_description="quality",
        )


def test_token_estimator_is_conservative_for_legal_identifiers() -> None:
    text = "TC/0001/26 Artículo 53 Ley 137-11 RD$ 12,500.00"
    estimated = estimate_legal_text_tokens(text)

    assert estimated > 0
    assert estimated >= len(text.encode("utf-8")) // 4



def test_record_scoped_batching_counts_only_questions_sent_with_each_batch() -> None:
    records = tuple(
        DecisionRecord(
            record_id=f"r{index}",
            text=("Artículo 53 de la Ley 137-11. " * 120),
        )
        for index in range(6)
    )

    def question_factory(record_ids: tuple[str, ...]) -> dict[str, JsonObject]:
        return {
            f"{record_id}__quality": {
                "type": "choice",
                "instructions": "Clasifique la calidad de transcripción.",
                "criteria": {
                    "acceptable": "usable",
                    "material_error": "damaged",
                    "uncertain": "uncertain",
                },
            }
            for record_id in record_ids
        }

    policy = DecisionBatchPolicy(
        max_context_tokens=32_000,
        target_total_tokens=24_000,
        reserved_instruction_tokens=4_000,
        max_records_per_batch=20,
    )
    batches = plan_record_scoped_decision_batches(
        records,
        question_factory=question_factory,
        state_description="Dominican legal-text quality routing.",
        policy=policy,
    )

    assert batches
    assert all(
        batch.estimated_total_tokens <= policy.target_total_tokens
        for batch in batches
    )
    assert tuple(
        record.record_id
        for batch in batches
        for record in batch.records
    ) == tuple(record.record_id for record in records)
