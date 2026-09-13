from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_discovery import (
    DocumentStructureHypothesis,
    IndexReferenceInvestigation,
    InvestigationPageEvidence,
)
from jurisnexo.ingestion.document_environment import (
    DocumentEnvironment,
    DocumentEnvironmentError,
)
from jurisnexo.ingestion.evidence_validation import (
    EvidenceValidationError,
    validate_index_reference_evidence,
)
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditCheck,
    StructureAuditResult,
    validate_structure_audit_evidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _hypothesis(evidence: InvestigationPageEvidence) -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis(
        artifact_class="bulletin",
        family_name_candidate="Boletín Judicial",
        structure_confidence=0.8,
        has_index=True,
        index_reference_investigations=[
            IndexReferenceInvestigation(
                reference_as_printed=353,
                expected_description="decision listed in SUMARIO",
                resolution_status="unresolved",
                evidence_pages=[evidence],
                observed_description="terminal source page inspected",
                explanation="printed identity is not resolved for this view page",
                confidence=0.6,
            )
        ],
        status="review_required",
    )


def test_view_page_without_printed_identity_is_valid_evidence() -> None:
    environment = DocumentEnvironment(("terminal decision text",))
    evidence = InvestigationPageEvidence(view_page=1, printed_page=None)

    validate_index_reference_evidence(
        hypothesis=_hypothesis(evidence),
        environment=environment,
    )


def test_model_cannot_invent_printed_identity_for_unresolved_view_page() -> None:
    environment = DocumentEnvironment(("terminal decision text",))
    evidence = InvestigationPageEvidence(view_page=1, printed_page=353)

    with pytest.raises(EvidenceValidationError, match="has no resolved printed page"):
        validate_index_reference_evidence(
            hypothesis=_hypothesis(evidence),
            environment=environment,
        )


def test_auditor_accepts_view_only_evidence_but_rejects_invented_printed_page() -> None:
    environment = DocumentEnvironment(("terminal decision text",))
    good = StructureAuditResult(
        state="APPROVED",
        checks=[
            StructureAuditCheck(
                kind="end_boundary",
                status="supported",
                target="terminal page",
                explanation="source-backed terminal content",
                evidence_pages=[InvestigationPageEvidence(view_page=1, printed_page=None)],
            )
        ],
        summary="checked terminal boundary",
    )
    validate_structure_audit_evidence(audit=good, environment=environment)

    bad = good.model_copy(
        update={
            "checks": [
                StructureAuditCheck(
                    kind="end_boundary",
                    status="supported",
                    target="terminal page",
                    explanation="incorrect printed identity",
                    evidence_pages=[InvestigationPageEvidence(view_page=1, printed_page=353)],
                )
            ]
        }
    )
    with pytest.raises(DocumentEnvironmentError, match="has no resolved printed page"):
        validate_structure_audit_evidence(audit=bad, environment=environment)
