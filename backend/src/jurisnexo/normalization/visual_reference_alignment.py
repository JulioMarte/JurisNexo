from __future__ import annotations

from dataclasses import asdict, dataclass

from jurisnexo.normalization.gold import (
    ReferenceTextHealth,
    TextFidelityScore,
    assess_reference_text_health,
    score_text_fidelity,
)


@dataclass(frozen=True, slots=True)
class VisualReferencePolicy:
    minimum_native_characters: int = 800
    minimum_ocr_characters: int = 600
    minimum_ocr_mean_confidence: float = 85.0
    maximum_word_error_rate: float = 0.08
    maximum_character_error_rate: float = 0.05
    minimum_token_content_recall: float = 0.985
    minimum_token_content_precision: float = 0.985
    minimum_token_order_preservation: float = 0.97
    minimum_legal_critical_recall: float = 1.0


@dataclass(frozen=True, slots=True)
class VisualReferenceAssessment:
    accepted: bool
    rejection_reasons: tuple[str, ...]
    native_health: ReferenceTextHealth
    score: TextFidelityScore
    ocr_character_count: int
    ocr_mean_confidence: float | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "rejection_reasons": list(self.rejection_reasons),
            "native_health": asdict(self.native_health),
            "score": {
                "character_error_rate": self.score.character_error_rate,
                "word_error_rate": self.score.word_error_rate,
                "token_content_recall": self.score.token_content_recall,
                "token_content_precision": self.score.token_content_precision,
                "token_content_f1": self.score.token_content_f1,
                "token_order_preservation": self.score.token_order_preservation,
                "legal_critical_recall": self.score.legal_critical_recall,
            },
            "ocr_character_count": self.ocr_character_count,
            "ocr_mean_confidence": self.ocr_mean_confidence,
        }


def assess_visual_reference_alignment(
    *,
    native_text: str,
    ocr_text: str,
    ocr_mean_confidence: float | None,
    policy: VisualReferencePolicy = VisualReferencePolicy(),
) -> VisualReferenceAssessment:
    native_health = assess_reference_text_health(native_text)
    score = score_text_fidelity(
        expected_text=native_text,
        candidate_text=ocr_text,
    )
    reasons: list[str] = []

    if not native_health.is_reliable:
        reasons.extend(native_health.risk_flags)
    if len(native_text.strip()) < policy.minimum_native_characters:
        reasons.append("native_text_too_short")
    if len(ocr_text.strip()) < policy.minimum_ocr_characters:
        reasons.append("ocr_text_too_short")
    if (
        ocr_mean_confidence is None
        or ocr_mean_confidence < policy.minimum_ocr_mean_confidence
    ):
        reasons.append("ocr_confidence_too_low")
    if score.word_error_rate > policy.maximum_word_error_rate:
        reasons.append("word_error_rate_too_high")
    if score.character_error_rate > policy.maximum_character_error_rate:
        reasons.append("character_error_rate_too_high")
    if score.token_content_recall < policy.minimum_token_content_recall:
        reasons.append("token_recall_too_low")
    if score.token_content_precision < policy.minimum_token_content_precision:
        reasons.append("token_precision_too_low")
    if score.token_order_preservation < policy.minimum_token_order_preservation:
        reasons.append("token_order_too_low")
    if score.legal_critical_recall < policy.minimum_legal_critical_recall:
        reasons.append("legal_critical_recall_too_low")

    return VisualReferenceAssessment(
        accepted=not reasons,
        rejection_reasons=tuple(reasons),
        native_health=native_health,
        score=score,
        ocr_character_count=len(ocr_text),
        ocr_mean_confidence=ocr_mean_confidence,
    )
