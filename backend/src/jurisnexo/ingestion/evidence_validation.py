from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.ingestion.document_discovery import (
    DocumentStructureHypothesis,
    InvestigationPageEvidence,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError


@dataclass(frozen=True, slots=True)
class EvidenceValidationError(ValueError):
    """Raised when model-produced evidence does not match the source environment."""

    message: str

    def __str__(self) -> str:
        return self.message


def _validate_evidence_pages(
    *,
    evidence_pages: list[InvestigationPageEvidence],
    environment: DocumentEnvironment,
    label: str,
) -> None:
    for evidence_index, evidence in enumerate(evidence_pages, start=1):
        item_label = f"{label}, evidence item {evidence_index}"
        try:
            page = environment.get_page(evidence.view_page)
        except DocumentEnvironmentError as exc:
            raise EvidenceValidationError(
                f"{item_label}: view page {evidence.view_page} is not in the document environment"
            ) from exc

        if page.printed_page_number is None:
            if evidence.printed_page is not None:
                raise EvidenceValidationError(
                    f"{item_label}: view page {evidence.view_page} has no resolved printed page; "
                    f"model claimed printed page {evidence.printed_page}"
                )
        elif evidence.printed_page != page.printed_page_number:
            raise EvidenceValidationError(
                f"{item_label}: view page {evidence.view_page} resolves to printed page "
                f"{page.printed_page_number}, not claimed printed page {evidence.printed_page}"
            )

        if evidence.source_reference is not None:
            if page.source_reference is None:
                raise EvidenceValidationError(
                    f"{item_label}: source provenance was claimed but the environment has none"
                )
            if page.source_reference != evidence.source_reference:
                raise EvidenceValidationError(
                    f"{item_label}: source provenance does not match the document environment"
                )


def validate_index_reference_evidence(
    *,
    hypothesis: DocumentStructureHypothesis,
    environment: DocumentEnvironment,
) -> None:
    """Validate every typed structure evidence item against the immutable source view.

    The historical function name is retained for compatibility. Validation now covers index
    investigations, decision-work-unit boundary evidence, and durable structure findings. Printed
    identity is checked whenever the environment resolved it; otherwise models must preserve a null
    printed identity rather than inventing pagination.
    """

    for investigation_index, investigation in enumerate(
        hypothesis.index_reference_investigations,
        start=1,
    ):
        _validate_evidence_pages(
            evidence_pages=investigation.evidence_pages,
            environment=environment,
            label=f"index investigation {investigation_index}",
        )

    for unit_index, unit in enumerate(hypothesis.decision_work_units, start=1):
        _validate_evidence_pages(
            evidence_pages=unit.boundary_evidence_pages,
            environment=environment,
            label=f"decision work unit {unit_index} ({unit.work_unit_id})",
        )

    for finding_index, finding in enumerate(hypothesis.structure_findings, start=1):
        _validate_evidence_pages(
            evidence_pages=finding.evidence_pages,
            environment=environment,
            label=f"structure finding {finding_index} ({finding.finding_id})",
        )
