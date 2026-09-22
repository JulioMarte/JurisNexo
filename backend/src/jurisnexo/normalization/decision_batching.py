from __future__ import annotations

import math
from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    record_id: str
    text: str
    metadata: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class DecisionBatch:
    records: tuple[DecisionRecord, ...]
    estimated_record_tokens: int
    estimated_total_tokens: int


@dataclass(frozen=True, slots=True)
class DecisionBatchPolicy:
    """Conservative context budgeting for System One decision models.

    JEV currently exposes a 32k context window. JurisNexo deliberately targets
    a lower working budget so state descriptions, question definitions and
    provider serialization have headroom.
    """

    max_context_tokens: int = 32_000
    target_total_tokens: int = 24_000
    reserved_instruction_tokens: int = 4_000
    max_records_per_batch: int = 20
    minimum_record_tokens: int = 32

    def __post_init__(self) -> None:
        if self.max_context_tokens < 1:
            raise ValueError("max_context_tokens must be positive")
        if not 0 < self.target_total_tokens < self.max_context_tokens:
            raise ValueError(
                "target_total_tokens must be below max_context_tokens"
            )
        if not 0 < self.reserved_instruction_tokens < self.target_total_tokens:
            raise ValueError(
                "reserved_instruction_tokens must leave room for records"
            )
        if self.max_records_per_batch < 1:
            raise ValueError("max_records_per_batch must be positive")


def estimate_legal_text_tokens(text: str) -> int:
    """Estimate tokens conservatively without adding a tokenizer dependency.

    Spanish legal text commonly compresses to several characters per token,
    but citations, identifiers and punctuation are token-expensive. Using
    UTF-8 bytes / 3 plus a fixed floor intentionally overestimates many normal
    paragraphs so batching stays away from the provider's hard context edge.
    """

    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


def estimate_question_tokens(questions: dict[str, JsonObject]) -> int:
    serialized = repr(questions)
    return estimate_legal_text_tokens(serialized)


def plan_decision_batches(
    records: tuple[DecisionRecord, ...],
    *,
    questions: dict[str, JsonObject],
    state_description: str,
    policy: DecisionBatchPolicy | None = None,
) -> tuple[DecisionBatch, ...]:
    policy = policy or DecisionBatchPolicy()
    if not records:
        return ()

    question_tokens = estimate_question_tokens(questions)
    fixed_tokens = (
        policy.reserved_instruction_tokens
        + question_tokens
        + estimate_legal_text_tokens(state_description)
    )
    if fixed_tokens >= policy.target_total_tokens:
        raise ValueError(
            "decision questions/state consume the entire target context budget"
        )
    record_budget = policy.target_total_tokens - fixed_tokens

    batches: list[DecisionBatch] = []
    current: list[DecisionRecord] = []
    current_tokens = 0

    for record in records:
        record_tokens = max(
            policy.minimum_record_tokens,
            estimate_legal_text_tokens(record.text),
        )
        if record_tokens > record_budget:
            raise ValueError(
                f"record {record.record_id!r} exceeds the safe JEV batch budget"
            )

        would_exceed_tokens = current_tokens + record_tokens > record_budget
        would_exceed_records = len(current) >= policy.max_records_per_batch
        if current and (would_exceed_tokens or would_exceed_records):
            batches.append(
                DecisionBatch(
                    records=tuple(current),
                    estimated_record_tokens=current_tokens,
                    estimated_total_tokens=fixed_tokens + current_tokens,
                )
            )
            current = []
            current_tokens = 0

        current.append(record)
        current_tokens += record_tokens

    if current:
        batches.append(
            DecisionBatch(
                records=tuple(current),
                estimated_record_tokens=current_tokens,
                estimated_total_tokens=fixed_tokens + current_tokens,
            )
        )

    for batch in batches:
        if batch.estimated_total_tokens >= policy.max_context_tokens:
            raise AssertionError("planned batch exceeds model context window")
    return tuple(batches)
