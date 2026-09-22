from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.decisions import (
    DecisionQuestion,
    DecisionResult,
    DecisionUsage,
)
from jurisnexo.normalization.jev_claims import (
    EvidenceClaim,
    evaluate_claim_support_batch,
)


@dataclass
class _FakeClaimProvider:
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
        answers: dict[str, JsonObject] = {}
        for record in records:
            record_id = record["id"]
            if record_id.endswith("supported"):
                distribution: dict[str, float] = {
                    "supported": 0.95,
                    "contradicted": 0.03,
                    "insufficient": 0.02,
                }
            else:
                distribution = {
                    "supported": 0.04,
                    "contradicted": 0.92,
                    "insufficient": 0.04,
                }
            selected = (
                "supported"
                if distribution["supported"] > distribution["contradicted"]
                else "contradicted"
            )
            answer: JsonObject = {
                "type": "choice",
                "choice": selected,
                "confidence": max(distribution.values()),
                "probabilities": distribution,
            }
            answers[record_id] = answer

        assert set(questions) == set(answers)
        return DecisionResult(
            answers=answers,
            provider="fake",
            model="fake-jev",
            model_version="fake-jev",
            response_id="claim-eval",
            usage=DecisionUsage(
                input_tokens=400,
                output_tokens=0,
                total_tokens=400,
            ),
            cost_usd=0.00002,
        )


def test_claim_verification_preserves_probabilities_and_usage() -> None:
    evaluation = evaluate_claim_support_batch(
        _FakeClaimProvider(),
        claims=(
            EvidenceClaim(
                claim_id="case_supported",
                evidence="Sentencia TC/0001/26.",
                proposed_value="TC/0001/26",
                field_name="decision_identifier",
            ),
            EvidenceClaim(
                claim_id="case_contradicted",
                evidence="Sentencia TC/0001/26.",
                proposed_value="TC/0009/26",
                field_name="decision_identifier",
            ),
        ),
    )

    assert len(evaluation.decisions) == 2
    supported, contradicted = evaluation.decisions
    assert supported.support_probability == 0.95
    assert contradicted.contradiction_probability == 0.92
    assert len(evaluation.telemetry) == 1
    assert evaluation.telemetry[0].input_tokens == 400
    assert evaluation.telemetry[0].cost_usd == 0.00002
