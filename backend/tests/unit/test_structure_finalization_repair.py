# pyright: reportPrivateUsage=false
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from jurisnexo.ingestion.document_discovery import (
    DecisionWorkUnit,
    InvestigationPageEvidence,
    StructureFinding,
    StructureFindingAttribute,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError
from jurisnexo.ingestion.sdk_structure_agent import (
    _document_tool_error_feedback,
    _scope_reminder,
    _structure_finalization_error_feedback,
)
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditCheck,
    StructureAuditResult,
    StructureFindingReview,
    _audit_finalization_error_feedback,
    _validate_finding_reviews_against_candidate,
)
from jurisnexo.ingestion.structure_trace import StructureToolTraceRecorder

pytestmark = [pytest.mark.unit]


def _fake_wrapper(*, max_attempts: int = 3) -> Any:
    context = SimpleNamespace(
        environment=DocumentEnvironment(pages=("page one",)),
        finalization_errors=[],
        max_finalization_repair_attempts=max_attempts,
        trace_recorder=StructureToolTraceRecorder(),
    )
    return cast(Any, SimpleNamespace(context=context))


def test_structure_finalization_error_returns_model_visible_repair_feedback() -> None:
    wrapper = _fake_wrapper()
    error = ModelBehaviorError("Invalid JSON input for tool finalize_structure_hypothesis")

    feedback = _structure_finalization_error_feedback(wrapper, error)

    assert "FINALIZATION_REJECTED" in feedback
    assert "DO NOT repeat searches or page reads" in feedback
    assert "Repair attempt 1 of 3" in feedback
    assert len(wrapper.context.trace_recorder.events) == 1
    assert wrapper.context.trace_recorder.events[0].status == "error"


def test_structure_finalization_repair_is_bounded() -> None:
    wrapper = _fake_wrapper(max_attempts=2)
    error = ModelBehaviorError("Invalid JSON input for tool finalize_structure_hypothesis")

    _structure_finalization_error_feedback(wrapper, error)
    with pytest.raises(ModelBehaviorError, match="Invalid JSON input"):
        _structure_finalization_error_feedback(wrapper, error)


def test_audit_finalization_error_returns_repair_feedback() -> None:
    wrapper = _fake_wrapper()
    error = ModelBehaviorError("Invalid JSON input for tool finalize_structure_audit")

    feedback = _audit_finalization_error_feedback(wrapper, error)

    assert "FINALIZATION_REJECTED" in feedback
    assert "DO NOT repeat page reads or searches" in feedback
    assert "Repair attempt 1 of 3" in feedback


def test_document_environment_errors_are_returned_to_agent_as_evidence() -> None:
    wrapper = _fake_wrapper()

    feedback = _document_tool_error_feedback(
        wrapper,
        DocumentEnvironmentError("printed page 360 is not resolved in this document view"),
    )

    assert "TOOL_REQUEST_REJECTED" in feedback
    assert "recoverable document-navigation condition" in feedback
    assert "do not repeat the identical request" in feedback
    assert "printed page 360" in feedback


def test_unexpected_tool_errors_still_fail_loudly() -> None:
    wrapper = _fake_wrapper()

    with pytest.raises(RuntimeError, match="programming defect"):
        _document_tool_error_feedback(wrapper, RuntimeError("programming defect"))


def test_scope_drift_reminder_warns_without_blocking_search() -> None:
    context = cast(
        Any,
        SimpleNamespace(
            search_queries=set(),
            scope_reminder_after_unique_searches=2,
        ),
    )

    assert _scope_reminder(context, "SUMARIO", "first result") == "first result"
    assert _scope_reminder(context, "Panteleón", "second result") == "second result"
    reminded = _scope_reminder(context, "Arias Lora", "third result")

    assert reminded.startswith("third result")
    assert "SCOPE_REMINDER" in reminded
    assert "Continue searching only when" in reminded


def test_decision_work_unit_allows_index_only_handoff_without_inventing_boundary() -> None:
    unit = DecisionWorkUnit(
        work_unit_id="index-001",
        index_ordinal=1,
        index_label="Recurso de casación de ejemplo",
        index_reference_printed_page=183,
        confidence=0.6,
        status="index_only",
    )

    assert unit.candidate_start_view_page is None
    assert unit.index_reference_printed_page == 183


def test_candidate_work_unit_requires_a_candidate_start_page() -> None:
    with pytest.raises(ValidationError, match="candidate_start_view_page"):
        DecisionWorkUnit(
            work_unit_id="candidate-001",
            index_ordinal=1,
            index_label="Entrada",
            confidence=0.9,
            status="candidate",
        )


def test_structure_finding_carries_machine_readable_downstream_context() -> None:
    finding = StructureFinding(
        finding_id="pagination-offset",
        kind="pagination_transform",
        statement="Printed pagination is offset from the document view.",
        operational_impact="Resolve index references through the printed-page map.",
        evidence_basis="page",
        evidence_pages=[InvestigationPageEvidence(view_page=6, printed_page=183)],
        attributes=[StructureFindingAttribute(key="view_to_printed_offset", value="177")],
        downstream_instructions=["Prefer printed-page lookup for index destinations."],
        confidence=0.97,
    )

    assert finding.attributes[0].value == "177"
    assert finding.material is True


def test_auditor_can_amend_finding_but_not_cleanly_approve_the_change() -> None:
    replacement = StructureFinding(
        finding_id="source-completeness",
        kind="source_completeness",
        statement="The scan appears to be an excerpt of a larger printed volume.",
        operational_impact="Do not infer missing printed pages from absent view pages.",
        evidence_basis="page",
        evidence_pages=[InvestigationPageEvidence(view_page=181, printed_page=358)],
        confidence=0.8,
    )
    review = StructureFindingReview(
        finding_id="source-completeness",
        action="amended",
        explanation="The source supports excerpt status but not a precise missing-page count.",
        evidence_pages=[InvestigationPageEvidence(view_page=181, printed_page=358)],
        replacement_finding=replacement,
    )

    with pytest.raises(ValidationError, match="APPROVED"):
        StructureAuditResult(
            state="APPROVED",
            checks=[
                StructureAuditCheck(
                    kind="artifact_rendering_mode",
                    status="supported",
                    target="scan",
                    explanation="Scanned artifact.",
                )
            ],
            finding_reviews=[review],
            summary="Needs correction.",
        )


def test_clean_approval_requires_every_candidate_finding_reviewed() -> None:
    audit = StructureAuditResult(
        state="APPROVED",
        checks=[
            StructureAuditCheck(
                kind="artifact_rendering_mode",
                status="supported",
                target="scan",
                explanation="Scanned artifact.",
            )
        ],
        finding_reviews=[
            StructureFindingReview(
                finding_id="pagination-offset",
                action="confirmed",
                explanation="Offset reproduced independently.",
            )
        ],
        summary="Structure is sound.",
    )

    with pytest.raises(ValueError, match="missing"):
        _validate_finding_reviews_against_candidate(
            audit=audit,
            candidate_finding_ids=("pagination-offset", "source-completeness"),
        )
