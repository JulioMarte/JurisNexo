from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import TextFidelityScore, score_text_fidelity


@dataclass(frozen=True, slots=True)
class SourceTextReference:
    text: str
    authority: str
    risk_flags: tuple[str, ...] = ()

    @property
    def reliable(self) -> bool:
        return bool(self.text.strip()) and not self.risk_flags


class SourceTextReferenceExtractor(Protocol):
    def extract(
        self,
        source: bytes,
        inspection: FormatInspection,
    ) -> SourceTextReference | None: ...


@dataclass(frozen=True, slots=True)
class SourceFidelityThresholds:
    max_word_error_rate: float = 0.10
    min_token_content_recall: float = 0.98
    min_token_content_precision: float = 0.98
    min_legal_critical_recall: float = 1.0


@dataclass(frozen=True, slots=True)
class SourceFidelityAssessment:
    authority: str
    reference_reliable: bool
    reference_risk_flags: tuple[str, ...]
    score: TextFidelityScore | None
    risk_flags: tuple[str, ...]

    @property
    def requires_review(self) -> bool:
        return bool(self.risk_flags)


@dataclass(slots=True)
class DeterministicSourceFidelityChecker:
    extractor: SourceTextReferenceExtractor
    thresholds: SourceFidelityThresholds = SourceFidelityThresholds()

    def evaluate(
        self,
        *,
        source: bytes,
        inspection: FormatInspection,
        candidate_text: str,
    ) -> SourceFidelityAssessment | None:
        reference = self.extractor.extract(source, inspection)
        if reference is None:
            return None
        if not reference.reliable:
            return SourceFidelityAssessment(
                authority=reference.authority,
                reference_reliable=False,
                reference_risk_flags=reference.risk_flags,
                score=None,
                risk_flags=("source_reference_unreliable",),
            )

        score = score_text_fidelity(
            expected_text=reference.text,
            candidate_text=candidate_text,
        )
        risks: list[str] = []
        if score.word_error_rate > self.thresholds.max_word_error_rate:
            risks.append("source_word_error_rate")
        if score.token_content_recall < self.thresholds.min_token_content_recall:
            risks.append("source_content_recall")
        if score.token_content_precision < self.thresholds.min_token_content_precision:
            risks.append("source_content_precision")
        if score.legal_critical_recall < self.thresholds.min_legal_critical_recall:
            risks.append("source_legal_critical_loss")
        return SourceFidelityAssessment(
            authority=reference.authority,
            reference_reliable=True,
            reference_risk_flags=(),
            score=score,
            risk_flags=tuple(risks),
        )


def assessment_payload(
    assessment: SourceFidelityAssessment,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "authority": assessment.authority,
        "reference_reliable": assessment.reference_reliable,
        "reference_risk_flags": list(assessment.reference_risk_flags),
        "risk_flags": list(assessment.risk_flags),
    }
    score = assessment.score
    if score is None:
        return payload
    payload.update(
        {
            "character_error_rate": score.character_error_rate,
            "word_error_rate": score.word_error_rate,
            "token_content_recall": score.token_content_recall,
            "token_content_precision": score.token_content_precision,
            "token_order_preservation": score.token_order_preservation,
            "legal_critical_recall": score.legal_critical_recall,
        }
    )
    return payload
