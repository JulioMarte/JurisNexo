from __future__ import annotations

import pytest
from agents import FunctionTool
from pydantic import ValidationError

from jurisnexo.ingestion.decision_reconstruction import (
    DecisionBoundary,
    SourceFaithfulDecision,
    reconstruct_source_faithful_decision,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError
from jurisnexo.ingestion.sdk_extraction_agent import ExtractionAnnotations
from jurisnexo.ingestion.sdk_extraction_auditor import (
    ExtractionAuditResult,
    build_extraction_auditor,
    validate_extraction_audit_evidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _environment() -> DocumentEnvironment:
    return DocumentEnvironment(
        (
            "PRIOR CASE TAIL",
            "SENTENCIA 12-2026\nJuan Pérez contra ACME",
            "La Corte decide ACOGER el recurso.",
            "NEXT CASE HEADER",
        ),
        printed_page_numbers=(10, 11, 12, 13),
        source_references=("src:10", "src:11", "src:12", "src:13"),
    )


def _decision() -> SourceFaithfulDecision:
    return reconstruct_source_faithful_decision(
        environment=_environment(),
        boundary=DecisionBoundary(start_view_page=2, end_view_page=3),
    )


def _annotations() -> ExtractionAnnotations:
    exact = "SENTENCIA 12-2026"
    return ExtractionAnnotations.model_validate(
        {
            "metadata": [
                {
                    "field": "decision_number",
                    "value": "12-2026",
                    "confidence": 0.99,
                    "evidence": [
                        {
                            "view_page": 2,
                            "char_start": 0,
                            "char_end": len(exact),
                            "exact_text": exact,
                        }
                    ],
                }
            ]
        }
    )


def test_extraction_auditor_is_separate_agent_with_source_tools() -> None:
    auditor = build_extraction_auditor(model="gpt-5.6-luna")

    assert auditor.name == "JurisNexo Extraction Auditor"
    assert auditor.output_type == ExtractionAuditResult
    tools = [tool for tool in auditor.tools if isinstance(tool, FunctionTool)]
    assert {tool.name for tool in tools} == {
        "get_candidate_page",
        "get_source_page",
        "get_source_pages",
    }


def test_verified_state_allows_commit_only_without_material_gaps() -> None:
    audit = ExtractionAuditResult.model_validate(
        {
            "state": "VERIFIED",
            "checks": [
                {
                    "kind": "field_support",
                    "status": "supported",
                    "target": "decision_number=12-2026",
                    "explanation": "The number appears in the candidate decision heading.",
                    "evidence": [
                        {
                            "view_page": 2,
                            "printed_page": 11,
                            "source_reference": "src:11",
                            "exact_excerpt": "SENTENCIA 12-2026",
                        }
                    ],
                }
            ],
            "summary": "Material extracted field independently verified.",
        }
    )

    assert audit.allows_canonical_commit is True
    validate_extraction_audit_evidence(audit=audit, environment=_environment())


def test_verified_cannot_hide_unresolved_check() -> None:
    with pytest.raises(ValidationError, match="VERIFIED cannot contain"):
        ExtractionAuditResult.model_validate(
            {
                "state": "VERIFIED",
                "checks": [
                    {
                        "kind": "boundary_leakage",
                        "status": "unresolved",
                        "target": "end boundary",
                        "explanation": "Need to inspect next page.",
                    }
                ],
                "summary": "Not resolved.",
            }
        )


def test_more_investigation_requires_focused_follow_up() -> None:
    with pytest.raises(ValidationError, match="requires focused follow-up"):
        ExtractionAuditResult.model_validate(
            {
                "state": "MORE_INVESTIGATION_REQUIRED",
                "checks": [
                    {
                        "kind": "unresolved_region",
                        "status": "unresolved",
                        "target": "blank source page",
                        "explanation": "Image review is required.",
                    }
                ],
                "summary": "Source gap remains unresolved.",
            }
        )


def test_rejected_requires_source_backed_contradiction() -> None:
    with pytest.raises(ValidationError, match="REJECTED requires"):
        ExtractionAuditResult.model_validate(
            {
                "state": "REJECTED",
                "checks": [],
                "summary": "Unsupported rejection is forbidden.",
            }
        )


def test_audit_evidence_must_match_real_source_page_identity() -> None:
    audit = ExtractionAuditResult.model_validate(
        {
            "state": "REJECTED",
            "checks": [
                {
                    "kind": "boundary_leakage",
                    "status": "contradicted",
                    "target": "end boundary",
                    "explanation": "Neighbor evidence contradicts boundary.",
                    "evidence": [
                        {
                            "view_page": 4,
                            "printed_page": 999,
                            "source_reference": "src:13",
                            "exact_excerpt": "NEXT CASE HEADER",
                        }
                    ],
                }
            ],
            "summary": "Boundary rejected.",
        }
    )

    with pytest.raises(DocumentEnvironmentError, match="printed page identity"):
        validate_extraction_audit_evidence(audit=audit, environment=_environment())


def test_candidate_fixture_is_deterministically_source_valid_before_audit() -> None:
    decision = _decision()
    annotations = _annotations()

    assert decision.boundary.start_view_page == 2
    assert annotations.metadata[0].value == "12-2026"
