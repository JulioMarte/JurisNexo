from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class DateEvidenceChannel(StrEnum):
    HEADER = "header"
    DECISION_FORMULA = "decision_formula"
    OFFICIAL_METADATA = "official_metadata"
    MANUAL_PRIMARY_TEXT = "manual_primary_text"
    LLM_ASSIST = "llm_assist"


class DateVerification(StrEnum):
    OBSERVED = "observed"
    OFFICIAL_METADATA_VERIFIED = "official_metadata_verified"
    PRIMARY_TEXT_VERIFIED = "primary_text_verified"


class DecisionDateStatus(StrEnum):
    VERIFIED_PRIMARY_TEXT = "verified_primary_text"
    VERIFIED_OFFICIAL_METADATA = "verified_official_metadata"
    PARSED_HIGH_CONFIDENCE = "parsed_high_confidence"
    PARSED_UNVERIFIED = "parsed_unverified"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DateCandidate:
    observation_key: str
    value: date
    channel: DateEvidenceChannel
    method_name: str
    verification: DateVerification = DateVerification.OBSERVED


@dataclass(frozen=True, slots=True)
class DecisionDateResolution:
    value: date | None
    status: DecisionDateStatus
    supporting_observation_keys: tuple[str, ...]
    selected_evidence_key: str | None
    distinct_channels: tuple[DateEvidenceChannel, ...]

    @property
    def promotable(self) -> bool:
        return self.status in {
            DecisionDateStatus.VERIFIED_PRIMARY_TEXT,
            DecisionDateStatus.VERIFIED_OFFICIAL_METADATA,
            DecisionDateStatus.PARSED_HIGH_CONFIDENCE,
        }


_VERIFICATION_PRIORITY = {
    DateVerification.OBSERVED: 0,
    DateVerification.OFFICIAL_METADATA_VERIFIED: 1,
    DateVerification.PRIMARY_TEXT_VERIFIED: 2,
}

_CHANNEL_PRIORITY = {
    DateEvidenceChannel.LLM_ASSIST: 0,
    DateEvidenceChannel.HEADER: 1,
    DateEvidenceChannel.DECISION_FORMULA: 2,
    DateEvidenceChannel.OFFICIAL_METADATA: 3,
    DateEvidenceChannel.MANUAL_PRIMARY_TEXT: 4,
}


def _best_candidate(candidates: list[DateCandidate]) -> DateCandidate:
    return max(
        candidates,
        key=lambda candidate: (
            _VERIFICATION_PRIORITY[candidate.verification],
            _CHANNEL_PRIORITY[candidate.channel],
            candidate.method_name,
            candidate.observation_key,
        ),
    )


def reconcile_decision_date(candidates: list[DateCandidate]) -> DecisionDateResolution:
    """Resolve date observations conservatively without mutating canonical case data.

    Any disagreement on the normalized date is treated as a conflict. A single
    unverified signal remains parsed-but-unverified. High-confidence parsed dates
    require agreement from at least two distinct non-LLM evidence channels.
    Explicit source verification outranks parsed confidence only after all observed
    candidates agree on the same normalized date.
    """

    if not candidates:
        return DecisionDateResolution(
            value=None,
            status=DecisionDateStatus.UNKNOWN,
            supporting_observation_keys=(),
            selected_evidence_key=None,
            distinct_channels=(),
        )

    values = {candidate.value for candidate in candidates}
    channels = tuple(sorted({candidate.channel for candidate in candidates}, key=str))
    keys = tuple(sorted({candidate.observation_key for candidate in candidates}))

    if len(values) != 1:
        return DecisionDateResolution(
            value=None,
            status=DecisionDateStatus.CONFLICTING,
            supporting_observation_keys=keys,
            selected_evidence_key=None,
            distinct_channels=channels,
        )

    value = next(iter(values))
    best = _best_candidate(candidates)

    if any(
        candidate.verification is DateVerification.PRIMARY_TEXT_VERIFIED
        for candidate in candidates
    ):
        status = DecisionDateStatus.VERIFIED_PRIMARY_TEXT
    elif any(
        candidate.verification is DateVerification.OFFICIAL_METADATA_VERIFIED
        for candidate in candidates
    ):
        status = DecisionDateStatus.VERIFIED_OFFICIAL_METADATA
    else:
        non_llm_channels = {
            candidate.channel
            for candidate in candidates
            if candidate.channel is not DateEvidenceChannel.LLM_ASSIST
        }
        status = (
            DecisionDateStatus.PARSED_HIGH_CONFIDENCE
            if len(non_llm_channels) >= 2
            else DecisionDateStatus.PARSED_UNVERIFIED
        )

    return DecisionDateResolution(
        value=value,
        status=status,
        supporting_observation_keys=keys,
        selected_evidence_key=best.observation_key,
        distinct_channels=channels,
    )
