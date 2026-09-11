from datetime import date

import pytest

from jurisnexo.ingestion.date_reconciliation import (
    DateCandidate,
    DateEvidenceChannel,
    DateVerification,
    DecisionDateStatus,
    reconcile_decision_date,
)

pytestmark = pytest.mark.unit


D = date(2025, 4, 30)


def candidate(
    key: str,
    *,
    value: date = D,
    channel: DateEvidenceChannel = DateEvidenceChannel.DECISION_FORMULA,
    verification: DateVerification = DateVerification.OBSERVED,
    method_name: str = "scj_decision_formula_date_v1",
) -> DateCandidate:
    return DateCandidate(
        observation_key=key,
        value=value,
        channel=channel,
        method_name=method_name,
        verification=verification,
    )


def test_no_candidates_remains_unknown_and_not_promotable() -> None:
    resolution = reconcile_decision_date([])

    assert resolution.value is None
    assert resolution.status is DecisionDateStatus.UNKNOWN
    assert resolution.promotable is False


def test_single_deterministic_signal_remains_unverified() -> None:
    resolution = reconcile_decision_date([candidate("a")])

    assert resolution.value == D
    assert resolution.status is DecisionDateStatus.PARSED_UNVERIFIED
    assert resolution.promotable is False


def test_two_distinct_non_llm_channels_agreeing_are_high_confidence() -> None:
    resolution = reconcile_decision_date(
        [
            candidate("header", channel=DateEvidenceChannel.HEADER, method_name="header_v1"),
            candidate("body", channel=DateEvidenceChannel.DECISION_FORMULA),
        ]
    )

    assert resolution.value == D
    assert resolution.status is DecisionDateStatus.PARSED_HIGH_CONFIDENCE
    assert resolution.promotable is True


def test_llm_agreement_does_not_upgrade_single_deterministic_channel() -> None:
    resolution = reconcile_decision_date(
        [
            candidate("body"),
            candidate(
                "llm",
                channel=DateEvidenceChannel.LLM_ASSIST,
                method_name="llm_date_extractor_v1",
            ),
        ]
    )

    assert resolution.status is DecisionDateStatus.PARSED_UNVERIFIED
    assert resolution.promotable is False


def test_any_date_disagreement_becomes_conflict_without_selected_value() -> None:
    resolution = reconcile_decision_date(
        [
            candidate("body"),
            candidate(
                "header",
                value=date(2025, 4, 29),
                channel=DateEvidenceChannel.HEADER,
                method_name="header_v1",
            ),
        ]
    )

    assert resolution.value is None
    assert resolution.status is DecisionDateStatus.CONFLICTING
    assert resolution.selected_evidence_key is None
    assert resolution.promotable is False


def test_verified_primary_text_requires_consensus_with_other_observations() -> None:
    resolution = reconcile_decision_date(
        [
            candidate(
                "manual",
                channel=DateEvidenceChannel.MANUAL_PRIMARY_TEXT,
                verification=DateVerification.PRIMARY_TEXT_VERIFIED,
                method_name="human_primary_text_review",
            ),
            candidate("body"),
        ]
    )

    assert resolution.status is DecisionDateStatus.VERIFIED_PRIMARY_TEXT
    assert resolution.selected_evidence_key == "manual"
    assert resolution.promotable is True


def test_even_verified_primary_text_is_blocked_by_a_conflicting_observation() -> None:
    resolution = reconcile_decision_date(
        [
            candidate(
                "manual",
                channel=DateEvidenceChannel.MANUAL_PRIMARY_TEXT,
                verification=DateVerification.PRIMARY_TEXT_VERIFIED,
                method_name="human_primary_text_review",
            ),
            candidate("body", value=date(2025, 4, 29)),
        ]
    )

    assert resolution.status is DecisionDateStatus.CONFLICTING
    assert resolution.value is None
    assert resolution.promotable is False


def test_verified_official_metadata_is_distinguished_from_primary_text() -> None:
    resolution = reconcile_decision_date(
        [
            candidate(
                "official",
                channel=DateEvidenceChannel.OFFICIAL_METADATA,
                verification=DateVerification.OFFICIAL_METADATA_VERIFIED,
                method_name="official_catalog_import_v1",
            )
        ]
    )

    assert resolution.status is DecisionDateStatus.VERIFIED_OFFICIAL_METADATA
    assert resolution.value == D
    assert resolution.promotable is True
