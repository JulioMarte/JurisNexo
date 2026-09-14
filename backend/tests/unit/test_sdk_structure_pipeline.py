from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.sdk_structure_agent import StructureAgentRunResult
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditorRunResult,
    StructureAuditResult,
)
from jurisnexo.ingestion.sdk_structure_pipeline import (
    StructurePipelineRound,
    StructurePipelineRunResult,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _hypothesis() -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis.model_validate(
        {
            "artifact_class": "bulletin",
            "family_name_candidate": "synthetic",
            "structure_confidence": 0.8,
            "has_index": True,
            "index_page_candidates": [1],
            "segmentation_hypotheses": [],
            "candidate_segments": [],
            "metadata_hypotheses": [],
            "index_reference_investigations": [],
            "anomalies": [],
            "recommended_next_actions": [],
            "status": "candidate",
        }
    )


def _structure() -> StructureAgentRunResult:
    return StructureAgentRunResult(
        hypothesis=_hypothesis(),
        usage_total_tokens=10,
        last_agent_name="structure",
        tool_trace=(),
    )


def _audit(state: str) -> StructureAuditorRunResult:
    if state == "APPROVED":
        payload = {
            "state": "APPROVED",
            "checks": [
                {
                    "kind": "artifact_rendering_mode",
                    "status": "supported",
                    "target": "synthetic mode",
                    "explanation": "checked",
                }
            ],
            "summary": "clean approval",
        }
    elif state == "APPROVED_WITH_AMENDMENTS":
        payload = {
            "state": "APPROVED_WITH_AMENDMENTS",
            "checks": [
                {
                    "kind": "artifact_rendering_mode",
                    "status": "supported",
                    "target": "synthetic mode",
                    "explanation": "checked",
                }
            ],
            "amendments": ["Correct the candidate before extraction."],
            "summary": "approval requires correction",
        }
    else:
        payload = {
            "state": "MORE_INVESTIGATION_REQUIRED",
            "checks": [
                {
                    "kind": "end_boundary",
                    "status": "unresolved",
                    "target": "decision end",
                    "explanation": "needs neighboring pages",
                }
            ],
            "required_follow_up": ["Inspect the next printed-page neighborhood."],
            "summary": "material ambiguity remains",
        }
    return StructureAuditorRunResult(
        audit=StructureAuditResult.model_validate(payload),
        usage_total_tokens=5,
        last_agent_name="auditor",
        tool_trace=(),
    )


def _pipeline(state: str) -> StructurePipelineRunResult:
    return StructurePipelineRunResult(
        rounds=(
            StructurePipelineRound(
                round_number=0,
                structure=_structure(),
                audit=_audit(state),
            ),
        )
    )


def test_only_clean_approval_unlocks_extraction() -> None:
    assert _pipeline("APPROVED").extraction_allowed is True
    assert _pipeline("APPROVED_WITH_AMENDMENTS").extraction_allowed is False
    assert _pipeline("MORE_INVESTIGATION_REQUIRED").extraction_allowed is False


def test_amendments_and_unresolved_findings_require_reinvestigation() -> None:
    assert _pipeline("APPROVED").exhausted_reinvestigation is False
    assert _pipeline("APPROVED_WITH_AMENDMENTS").exhausted_reinvestigation is True
    assert _pipeline("MORE_INVESTIGATION_REQUIRED").exhausted_reinvestigation is True