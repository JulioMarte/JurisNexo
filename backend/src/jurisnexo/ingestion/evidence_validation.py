from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError


@dataclass(frozen=True, slots=True)
class EvidenceValidationError(ValueError):
    """Raised when model-produced evidence does not match the source environment."""

    message: str

    def __str__(self) -> str:
        return self.message


def validate_index_reference_evidence(
    *,
    hypothesis: DocumentStructureHypothesis,
    environment: DocumentEnvironment,
) -> None:
    """Prove that every typed index-reference evidence item exists in the source view.

    Printed/editorial identity is verified when the immutable workspace has resolved it. A real
    view page may legitimately have no resolved printed number; in that case the model must emit
    ``printed_page=null`` rather than inventing pagination. This preserves page evidence without
    turning an unresolved printed identity into false provenance.
    """

    for investigation_index, investigation in enumerate(
        hypothesis.index_reference_investigations,
        start=1,
    ):
        for evidence_index, evidence in enumerate(investigation.evidence_pages, start=1):
            label = (
                f"index investigation {investigation_index}, "
                f"evidence item {evidence_index}"
            )
            try:
                page = environment.get_page(evidence.view_page)
            except DocumentEnvironmentError as exc:
                raise EvidenceValidationError(
                    f"{label}: view page {evidence.view_page} is not in the document environment"
                ) from exc

            if page.printed_page_number is None:
                if evidence.printed_page is not None:
                    raise EvidenceValidationError(
                        f"{label}: view page {evidence.view_page} has no resolved printed page; "
                        f"model claimed printed page {evidence.printed_page}"
                    )
            elif evidence.printed_page != page.printed_page_number:
                raise EvidenceValidationError(
                    f"{label}: view page {evidence.view_page} resolves to printed page "
                    f"{page.printed_page_number}, not claimed printed page {evidence.printed_page}"
                )

            if evidence.source_reference is not None:
                if page.source_reference is None:
                    raise EvidenceValidationError(
                        f"{label}: source provenance was claimed but the environment has none"
                    )
                if page.source_reference != evidence.source_reference:
                    raise EvidenceValidationError(
                        f"{label}: source provenance does not match the document environment"
                    )
