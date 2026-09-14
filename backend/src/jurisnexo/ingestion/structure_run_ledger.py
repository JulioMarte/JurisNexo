from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from jurisnexo.ingestion.structure_trace import StructureToolTraceEvent
from jurisnexo.model_providers.usage_accounting import ModelTurnUsage

AgentRunRole = Literal[
    "structure_agent",
    "structure_auditor",
    "structure_reinvestigation",
]
AgentTerminalState = Literal["failed", "budget_exhausted", "blocked"]
StructurePipelineState = Literal[
    "structure_investigating",
    "structure_candidate",
    "structure_auditing",
    "structure_reinvestigating",
    "structure_verified",
    "structure_rejected",
    "source_quality_blocked",
    "failed",
    "cancelled",
]


class StructureRunLedger(Protocol):
    """Persistence boundary used by structure orchestration without depending on Postgres."""

    def create_structure_pipeline_run(
        self,
        *,
        ingestion_job_id: UUID,
        artifact_id: UUID,
        idempotency_key: str,
    ) -> UUID: ...

    def create_agent_run(
        self,
        *,
        ingestion_job_id: UUID,
        artifact_id: UUID,
        role: AgentRunRole,
        round_number: int,
        provider: str | None,
        model: str | None,
        prompt_sha256: str | None,
        tool_budget: dict[str, int],
        parent_run_id: UUID | None = None,
    ) -> UUID: ...

    def append_trace_event(self, *, run_id: UUID, event: StructureToolTraceEvent) -> None: ...

    def append_model_turn(self, *, run_id: UUID, event: ModelTurnUsage) -> None: ...

    def complete_agent_run(
        self,
        *,
        run_id: UUID,
        usage: dict[str, object],
        trace_object_ref: str | None = None,
        result_object_ref: str | None = None,
    ) -> None: ...

    def fail_agent_run(
        self,
        *,
        run_id: UUID,
        state: AgentTerminalState,
        error_type: str,
        error_message: str,
        usage: dict[str, object],
        trace_object_ref: str | None = None,
    ) -> None: ...

    def record_structure_pipeline_usage(
        self,
        *,
        pipeline_run_id: UUID,
        usage: dict[str, object],
    ) -> None: ...

    def transition_structure_pipeline(
        self,
        *,
        pipeline_run_id: UUID,
        target_state: StructurePipelineState,
        round_number: int | None = None,
        structure_run_id: UUID | None = None,
        audit_run_id: UUID | None = None,
        page_map_object_ref: str | None = None,
        structure_result_object_ref: str | None = None,
        audit_result_object_ref: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None: ...
