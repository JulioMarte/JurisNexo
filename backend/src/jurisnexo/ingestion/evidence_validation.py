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
    """Prove that every typed index-reference evidence pair exists in the source view.

    This is intentionally deterministic. The model may propose page identities, but it does
    not get authority to assert that a view page corresponds to a printed page or provenance
    reference. Those facts are checked against the immutable DocumentEnvironment.
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
                raise EvidenceValidationError(
                    f"{label}: view page {evidence.view_page} has no resolved printed page"
                )
            if page.printed_page_number != evidence.printed_page:
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
