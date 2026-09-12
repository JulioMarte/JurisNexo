from __future__ import annotations

import pytest
from agents import FunctionTool
from pydantic import ValidationError

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditResult,
    build_structure_auditor,
    validate_structure_audit_evidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _environment() -> DocumentEnvironment:
    return DocumentEnvironment(
        ("continuation", "SENTENCIA indexed target", "target continues"),
        printed_page_numbers=(353, 354, 355),
        source_references=("src:353", "src:354", "src:355"),
    )


def _hypothesis() -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis.model_validate(
        {
            "artifact_class": "bulletin",
            "family_name_candidate": "synthetic",
            "structure_confidence": 0.9,
            "has_index": True,
            "index_page_candidates": [1],
            "segmentation_hypotheses": [],
            "candidate_segments": [],
            "metadata_hypotheses": [],
            "index_reference_investigations": [
                {
                    "reference_as_printed": 353,
                    "expected_description": "indexed target",
                    "resolution_status": "confirmed_nearby",
                    "observed_decision_start_printed_page": 354,
                    "evidence_pages": [
                        {
                            "view_page": 1,
                            "printed_page": 353,
                            "role": "claimed_destination",
                            "source_reference": "src:353",
                        },
                        {
                            "view_page": 2,
                            "printed_page": 354,
                            "role": "observed_content",
                            "source_reference": "src:354",
                        },
                    ],
                    "observed_description": "target starts on 354",
                    "explanation": "353 continues the prior decision",
                    "confidence": 0.95,
                }
            ],
            "anomalies": [],
            "recommended_next_actions": [],
            "status": "candidate",
        }
    )


def test_structure_auditor_is_independent_agent_with_read_only_document_tools() -> None:
    auditor = build_structure_auditor(model="gpt-5.6-luna")

    assert auditor.name == "JurisNexo Structure Auditor"
    assert auditor.output_type == StructureAuditResult
    function_tools = [tool for tool in auditor.tools if isinstance(tool, FunctionTool)]
    assert len(function_tools) == len(auditor.tools)
    assert {tool.name for tool in function_tools} == {
        "get_page",
        "get_pages",
        "get_printed_page",
        "get_printed_pages",
        "search_text",
    }


def test_approved_audit_requires_independently_checked_evidence() -> None:
    audit = StructureAuditResult.model_validate(
        {
            "state": "APPROVED",
            "checks": [
                {
                    "kind": "index_destination",
                    "status": "supported",
                    "target": "index reference 353 resolves nearby to 354",
                    "explanation": "353 continues prior matter and 354 starts target",
                    "evidence_pages": [
                        {
                            "view_page": 1,
                            "printed_page": 353,
                            "role": "claimed_destination",
                            "source_reference": "src:353",
                        },
                        {
                            "view_page": 2,
                            "printed_page": 354,
                            "role": "observed_content",
                            "source_reference": "src:354",
                        },
                    ],
                }
            ],
            "summary": "Material discrepancy independently verified.",
        }
    )

    assert audit.allows_extraction is True
    validate_structure_audit_evidence(audit=audit, environment=_environment())


def test_approved_cannot_hide_unresolved_material_check() -> None:
    with pytest.raises(ValidationError, match="APPROVED cannot contain"):
        StructureAuditResult.model_validate(
            {
                "state": "APPROVED",
                "checks": [
                    {
                        "kind": "end_boundary",
                        "status": "unresolved",
                        "target": "decision end",
                        "explanation": "Need more neighboring pages.",
                    }
                ],
                "summary": "Not actually resolved.",
            }
        )


def test_more_investigation_requires_focused_follow_up() -> None:
    with pytest.raises(ValidationError, match="requires focused follow-up"):
        StructureAuditResult.model_validate(
            {
                "state": "MORE_INVESTIGATION_REQUIRED",
                "checks": [
                    {
                        "kind": "end_boundary",
                        "status": "unresolved",
                        "target": "decision end",
                        "explanation": "Need neighboring pages.",
                    }
                ],
                "summary": "Boundary remains unresolved.",
            }
        )


def test_rejected_requires_source_backed_contradiction() -> None:
    with pytest.raises(ValidationError, match="REJECTED requires"):
        StructureAuditResult.model_validate(
            {
                "state": "REJECTED",
                "checks": [],
                "summary": "Unsupported rejection is forbidden.",
            }
        )


def test_audit_evidence_validator_rejects_wrong_page_mapping() -> None:
    audit = StructureAuditResult.model_validate(
        {
            "state": "REJECTED",
            "checks": [
                {
                    "kind": "index_destination",
                    "status": "contradicted",
                    "target": "bad mapping",
                    "explanation": "Model claimed an impossible mapping.",
                    "evidence_pages": [
                        {
                            "view_page": 1,
                            "printed_page": 354,
                            "role": "observed_content",
                        }
                    ],
                }
            ],
            "summary": "Candidate evidence is invalid.",
        }
    )

    with pytest.raises(DocumentEnvironmentError, match="resolves to printed page 353"):
        validate_structure_audit_evidence(audit=audit, environment=_environment())


def test_hypothesis_fixture_remains_valid_for_auditor_input() -> None:
    hypothesis = _hypothesis()

    investigation = hypothesis.index_reference_investigations[0]
    assert investigation.reference_as_printed == 353
    assert investigation.observed_decision_start_printed_page == 354
