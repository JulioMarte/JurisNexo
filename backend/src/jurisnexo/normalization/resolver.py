from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ObservationMethod = Literal["native", "ocr", "visual", "human"]


@dataclass(frozen=True, slots=True)
class TextObservation:
    observation_id: str
    text: str
    method: ObservationMethod
    accepted: bool = False
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class TextCorrection:
    correction_id: str
    observation_id: str
    replacement_text: str
    accepted: bool


@dataclass(frozen=True, slots=True)
class ResolvedEvidenceText:
    text: str
    observation_id: str
    correction_id: str | None
    method: ObservationMethod


def resolve_evidence_text(
    observations: tuple[TextObservation, ...],
    corrections: tuple[TextCorrection, ...] = (),
) -> ResolvedEvidenceText:
    accepted = [item for item in observations if item.accepted]
    if len(accepted) != 1:
        raise ValueError("exactly one accepted text observation is required")
    observation = accepted[0]

    accepted_corrections = [
        item for item in corrections
        if item.observation_id == observation.observation_id and item.accepted
    ]
    if len(accepted_corrections) > 1:
        raise ValueError("multiple accepted corrections for one observation are ambiguous")
    if accepted_corrections:
        correction = accepted_corrections[0]
        return ResolvedEvidenceText(
            text=correction.replacement_text,
            observation_id=observation.observation_id,
            correction_id=correction.correction_id,
            method=observation.method,
        )
    return ResolvedEvidenceText(
        text=observation.text,
        observation_id=observation.observation_id,
        correction_id=None,
        method=observation.method,
    )


def normalize_search_text(evidence_text: str) -> str:
    return " ".join(evidence_text.split())
