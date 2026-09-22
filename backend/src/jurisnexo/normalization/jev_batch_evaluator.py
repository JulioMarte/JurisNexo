from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.decisions import DecisionProvider
from jurisnexo.normalization.decision_batching import (
    DecisionBatchPolicy,
    DecisionRecord,
    plan_record_scoped_decision_batches,
)
from jurisnexo.normalization.jev_quality import (
    TextQualityProbabilities,
    build_text_quality_questions,
    parse_text_quality_probabilities,
)


@dataclass(frozen=True, slots=True)
class JevRecordEvaluation:
    record_id: str
    probabilities: TextQualityProbabilities


@dataclass(frozen=True, slots=True)
class JevBatchTelemetry:
    batch_index: int
    record_count: int
    estimated_total_tokens: int
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    model: str


@dataclass(frozen=True, slots=True)
class JevBatchEvaluation:
    records: tuple[JevRecordEvaluation, ...]
    batches: tuple[JevBatchTelemetry, ...]


@dataclass(slots=True)
class JevBatchQualityEvaluator:
    provider: DecisionProvider
    policy: DecisionBatchPolicy = DecisionBatchPolicy()

    def evaluate(
        self,
        *,
        records: tuple[DecisionRecord, ...],
        state_description: str,
    ) -> JevBatchEvaluation:
        if not records:
            return JevBatchEvaluation(records=(), batches=())

        planned = plan_record_scoped_decision_batches(
            records,
            question_factory=lambda record_ids: build_text_quality_questions(
                record_ids=record_ids
            ),
            state_description=state_description,
            policy=self.policy,
        )

        evaluations: list[JevRecordEvaluation] = []
        telemetry: list[JevBatchTelemetry] = []

        for batch_index, batch in enumerate(planned):
            batch_ids = tuple(record.record_id for record in batch.records)
            questions = build_text_quality_questions(record_ids=batch_ids)
            result = self.provider.decide(
                state_description=state_description,
                records=tuple(
                    {
                        "id": record.record_id,
                        "record": _record_payload(record),
                    }
                    for record in batch.records
                ),
                questions=questions,
            )
            for record in batch.records:
                evaluations.append(
                    JevRecordEvaluation(
                        record_id=record.record_id,
                        probabilities=parse_text_quality_probabilities(
                            result.answers,
                            record_id=record.record_id,
                        ),
                    )
                )
            telemetry.append(
                JevBatchTelemetry(
                    batch_index=batch_index,
                    record_count=len(batch.records),
                    estimated_total_tokens=batch.estimated_total_tokens,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cost_usd=result.cost_usd,
                    model=result.model,
                )
            )

        return JevBatchEvaluation(
            records=tuple(evaluations),
            batches=tuple(telemetry),
        )


def _record_payload(record: DecisionRecord) -> str:
    if not record.metadata:
        return record.text
    metadata = _scalar_metadata(record.metadata)
    return f"Metadata: {metadata}\n\nNormalized text:\n{record.text}"


def _scalar_metadata(metadata: JsonObject) -> dict[str, object]:
    return {
        str(key): value
        for key, value in metadata.items()
        if value is None or isinstance(value, (bool, int, float, str))
    }
