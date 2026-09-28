from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.decisions import DecisionProvider
from jurisnexo.normalization.decision_batching import (
    DecisionBatchPolicy,
    DecisionRecord,
    plan_record_scoped_decision_batches,
)
from jurisnexo.normalization.jev_answers import choice_probability


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    claim_id: str
    evidence: str
    proposed_value: str
    field_name: str


@dataclass(frozen=True, slots=True)
class ClaimSupportDecision:
    claim_id: str
    support_probability: float
    contradiction_probability: float
    insufficient_probability: float


@dataclass(frozen=True, slots=True)
class ClaimSupportTelemetry:
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None


@dataclass(frozen=True, slots=True)
class ClaimSupportEvaluation:
    decisions: tuple[ClaimSupportDecision, ...]
    telemetry: tuple[ClaimSupportTelemetry, ...]


def build_claim_support_questions(
    claims: tuple[EvidenceClaim, ...],
) -> dict[str, JsonObject]:
    questions: dict[str, JsonObject] = {}
    for claim in claims:
        questions[claim.claim_id] = {
            "type": "choice",
            "instructions": (
                f'For the record with id "{claim.claim_id}", decide whether the '
                f'supplied evidence supports the proposed {claim.field_name!r} value. '
                "Judge only the "
                "evidence/value relationship; do not infer missing facts."
            ),
            "criteria": {
                "supported": (
                    "The evidence directly supports the proposed value."
                ),
                "contradicted": (
                    "The evidence directly conflicts with the proposed value."
                ),
                "insufficient": (
                    "The evidence does not contain enough information to support or "
                    "contradict the proposed value."
                ),
            },
        }
    return questions


def evaluate_claim_support(
    provider: DecisionProvider,
    *,
    claims: tuple[EvidenceClaim, ...],
) -> tuple[ClaimSupportDecision, ...]:
    return evaluate_claim_support_batch(
        provider,
        claims=claims,
    ).decisions


def evaluate_claim_support_batch(
    provider: DecisionProvider,
    *,
    claims: tuple[EvidenceClaim, ...],
    policy: DecisionBatchPolicy | None = None,
) -> ClaimSupportEvaluation:
    if not claims:
        return ClaimSupportEvaluation(decisions=(), telemetry=())

    state_description = (
        "Each record contains legal-document evidence plus a proposed extracted "
        "field value. Evaluate evidentiary support only."
    )
    records = tuple(
        DecisionRecord(
            record_id=claim.claim_id,
            text=(
                f"Field: {claim.field_name}\n"
                f"Proposed value: {claim.proposed_value}\n\n"
                f"Evidence:\n{claim.evidence}"
            ),
        )
        for claim in claims
    )
    claims_by_id = {claim.claim_id: claim for claim in claims}
    batches = plan_record_scoped_decision_batches(
        records,
        question_factory=lambda record_ids: build_claim_support_questions(
            tuple(claims_by_id[record_id] for record_id in record_ids)
        ),
        state_description=state_description,
        policy=policy,
    )

    decisions: list[ClaimSupportDecision] = []
    telemetry: list[ClaimSupportTelemetry] = []
    for batch in batches:
        batch_claims = tuple(
            claims_by_id[record.record_id] for record in batch.records
        )
        questions = build_claim_support_questions(batch_claims)
        result = provider.decide(
            state_description=state_description,
            records=tuple(
                {
                    "id": record.record_id,
                    "record": record.text,
                }
                for record in batch.records
            ),
            questions=questions,
        )

        for claim in batch_claims:
            answer = result.answers.get(claim.claim_id)
            if answer is None:
                raise RuntimeError(
                    f"decision provider omitted claim {claim.claim_id}"
                )
            decisions.append(
                ClaimSupportDecision(
                    claim_id=claim.claim_id,
                    support_probability=choice_probability(
                        answer,
                        "supported",
                    ),
                    contradiction_probability=choice_probability(
                        answer,
                        "contradicted",
                    ),
                    insufficient_probability=choice_probability(
                        answer,
                        "insufficient",
                    ),
                )
            )

        telemetry.append(
            ClaimSupportTelemetry(
                model=result.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                total_tokens=result.usage.total_tokens,
                cost_usd=result.cost_usd,
            )
        )

    return ClaimSupportEvaluation(
        decisions=tuple(decisions),
        telemetry=tuple(telemetry),
    )

