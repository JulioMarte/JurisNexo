from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from jurisnexo.corpus.legal_graph import RelationObservationInput
from jurisnexo.ingestion.sdk_extraction_agent import ExtractionAnnotations

ArtifactPageResolver = Callable[[int], UUID]


def reference_observations_from_extraction(
    *,
    source_document_id: UUID,
    annotations: ExtractionAnnotations,
    artifact_page_for_view_page: ArtifactPageResolver,
    ingestion_job_id: UUID | None = None,
    method_name: str = "extraction-reference-bridge-v1",
) -> tuple[RelationObservationInput, ...]:
    """Convert source-backed extraction references into unresolved citation observations.

    This bridge deliberately records only `cites`. The Extraction Agent is not allowed to
    infer treatment such as `interprets`, `applies`, or `overrules`. A later resolver/auditor
    must resolve the target document/provision and may propose a more specific semantic edge.
    """

    observations: list[RelationObservationInput] = []
    for reference in annotations.references:
        for span in reference.evidence:
            observations.append(
                RelationObservationInput(
                    source_document_id=source_document_id,
                    relation_type="cites",
                    raw_target_citation=reference.reference_as_written,
                    ingestion_job_id=ingestion_job_id,
                    assertion_method="explicit_primary_text",
                    method_name=method_name,
                    confidence=reference.confidence,
                    evidence_artifact_page_id=artifact_page_for_view_page(span.view_page),
                    evidence_excerpt=span.exact_text,
                    evidence_char_start=span.char_start,
                    evidence_char_end=span.char_end,
                )
            )
    return tuple(observations)
