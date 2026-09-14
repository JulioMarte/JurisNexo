from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

from jurisnexo.ingestion.document_discovery import DecisionWorkUnit
from jurisnexo.ingestion.sdk_structure_agent import (
    _scope_reminder,
    _structure_finalization_error_feedback,
)
from jurisnexo.ingestion.sdk_structure_auditor import _audit_finalization_error_feedback
from jurisnexo.ingestion.structure_trace import StructureToolTraceRecorder

pytestmark = [pytest.mark.unit]


def _fake_wrapper(*, max_attempts: int = 3) -> Any:
    context = SimpleNamespace(
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
