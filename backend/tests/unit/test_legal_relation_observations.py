from uuid import UUID

import pytest

from jurisnexo.ingestion.legal_relation_observations import (
    reference_observations_from_extraction,
)
from jurisnexo.ingestion.sdk_extraction_agent import (
    EvidenceSpan,
    ExtractionAnnotations,
    ReferenceAnnotation,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def test_reference_bridge_records_only_source_backed_unresolved_citations() -> None:
    source_document_id = UUID("00000000-0000-0000-0000-000000000101")
    artifact_page_id = UUID("00000000-0000-0000-0000-000000000201")
    annotations = ExtractionAnnotations(
        references=[
            ReferenceAnnotation(
                kind="statute_article",
                reference_as_written="artículo 17 de la Ley 123-20",
                confidence=0.91,
                evidence=[
                    EvidenceSpan(
                        view_page=4,
                        char_start=10,
                        char_end=39,
                        exact_text="artículo 17 de la Ley 123-20",
                    )
                ],
            )
        ]
    )

    observations = reference_observations_from_extraction(
        source_document_id=source_document_id,
        annotations=annotations,
        artifact_page_for_view_page=lambda view_page: (
            artifact_page_id if view_page == 4 else UUID(int=0)
        ),
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.source_document_id == source_document_id
    assert observation.relation_type == "cites"
    assert observation.target_document_id is None
    assert observation.target_provision_id is None
    assert observation.raw_target_citation == "artículo 17 de la Ley 123-20"
    assert observation.assertion_method == "explicit_primary_text"
    assert observation.evidence_artifact_page_id == artifact_page_id
    assert observation.evidence_excerpt == "artículo 17 de la Ley 123-20"


def test_reference_bridge_does_not_infer_semantic_treatment() -> None:
    annotations = ExtractionAnnotations(
        references=[
            ReferenceAnnotation(
                kind="cited_decision",
                reference_as_written="Sentencia TC/0001/26",
                confidence=0.8,
                evidence=[
                    EvidenceSpan(
                        view_page=1,
                        char_start=0,
                        char_end=20,
                        exact_text="Sentencia TC/0001/26",
                    )
                ],
            )
        ]
    )

    observations = reference_observations_from_extraction(
        source_document_id=UUID(int=1),
        annotations=annotations,
        artifact_page_for_view_page=lambda _: UUID(int=2),
    )

    assert observations[0].relation_type == "cites"
