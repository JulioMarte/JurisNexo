from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.decisions import DecisionProvider


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


def build_claim_support_questions(
    claims: tuple[EvidenceClaim, ...],
) -> dict[str, JsonObject]:
    questions: dict[str, JsonObject] = {}
    for claim in claims:
        questions[claim.claim_id] = {
            "type": "choice",
            "instructions": (
                f'For claim "{claim.claim_id}", decide whether the supplied evidence '
                f'supports the proposed {claim.field_name!r} value. Judge only the '
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
    if not claims:
        return ()

    questions = build_claim_support_questions(claims)
    result = provider.decide(
        state_description=(
            "Each record contains legal-document evidence plus a proposed extracted "
            "field value. Evaluate evidentiary support only."
        ),
        records=tuple(
            {
                "id": claim.claim_id,
                "record": (
                    f"Field: {claim.field_name}\n"
                    f"Proposed value: {claim.proposed_value}\n\n"
                    f"Evidence:\n{claim.evidence}"
                ),
            }
            for claim in claims
        ),
        questions=questions,
    )

    decisions: list[ClaimSupportDecision] = []
    for claim in claims:
        answer = result.answers.get(claim.claim_id)
        if answer is None:
            raise RuntimeError(
                f"decision provider omitted claim {claim.claim_id}"
            )
        choice = answer.get("choice")
        if not isinstance(choice, dict):
            raise RuntimeError(
                f"claim {claim.claim_id} did not return a choice distribution"
            )
        probabilities = dict(choice)
        decisions.append(
            ClaimSupportDecision(
                claim_id=claim.claim_id,
                support_probability=_probability(
                    probabilities.get("supported")
                ),
                contradiction_probability=_probability(
                    probabilities.get("contradicted")
                ),
                insufficient_probability=_probability(
                    probabilities.get("insufficient")
                ),
            )
        )
    return tuple(decisions)


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError("claim-support probability is not numeric")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise RuntimeError("claim-support probability is outside [0, 1]")
    return probability
