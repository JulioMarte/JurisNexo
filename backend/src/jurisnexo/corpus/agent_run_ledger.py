from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import psycopg

from jurisnexo.ingestion.structure_run_ledger import (
    AgentRunRole,
    AgentTerminalState,
    StructurePipelineState,
)
from jurisnexo.ingestion.structure_trace import StructureToolTraceEvent
from jurisnexo.model_providers.usage_accounting import ModelTurnUsage

AgentRunState = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "budget_exhausted",
    "cancelled",
    "blocked",
]

_ALLOWED_PIPELINE_TRANSITIONS: dict[StructurePipelineState, frozenset[StructurePipelineState]] = {
    "structure_investigating": frozenset({"structure_candidate", "failed", "cancelled"}),
    "structure_candidate": frozenset({"structure_auditing", "failed", "cancelled"}),
    "structure_auditing": frozenset(
        {
            "structure_verified",
            "structure_reinvestigating",
            "structure_rejected",
            "source_quality_blocked",
            "failed",
            "cancelled",
        }
    ),
    "structure_reinvestigating": frozenset({"structure_candidate", "failed", "cancelled"}),
    "structure_verified": frozenset(),
    "structure_rejected": frozenset(),
    "source_quality_blocked": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class InvalidPipelineTransition(RuntimeError):
    """Raised when an orchestration bug attempts to skip or reverse a durable state gate."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _usage_int(usage: dict[str, object], key: str) -> int:
    value = usage.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"usage field {key!r} must be a non-negative integer")
    return value


def _usage_cost(usage: dict[str, object]) -> Decimal | None:
    value = usage.get("estimated_cost_usd")
    if value is None:
        return None
    cost = Decimal(str(value))
    if cost < 0:
        raise ValueError("estimated_cost_usd must be non-negative")
    return cost


@dataclass(slots=True)
class PostgresAgentRunLedger:
    """Durable observable ledger for agent execution and structure-pipeline checkpoints."""

    connection: psycopg.Connection[Any]

    @staticmethod
    def _allocate_event_sequence(cursor: psycopg.Cursor[Any], *, run_id: UUID) -> int:
        cursor.execute(
            """
            update corpus.agent_runs
            set next_event_sequence = next_event_sequence + 1,
                updated_at = now()
            where id = %s
            returning next_event_sequence - 1
            """,
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(f"agent run {run_id} does not exist")
        sequence: int = row[0]
        return sequence

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
    ) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.agent_runs (
                    ingestion_job_id,
                    artifact_id,
                    parent_run_id,
                    role,
                    round_number,
                    state,
                    provider,
                    model,
                    prompt_sha256,
                    tool_budget,
                    started_at
                )
                values (%s, %s, %s, %s, %s, 'running', %s, %s, %s, %s::jsonb, now())
                returning id
                """,
                (
                    ingestion_job_id,
                    artifact_id,
                    parent_run_id,
                    role,
                    round_number,
                    provider,
                    model,
                    prompt_sha256,
                    _json(tool_budget),
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("agent run insert did not return an identifier")
            run_id: UUID = row[0]
            return run_id

    def append_trace_event(self, *, run_id: UUID, event: StructureToolTraceEvent) -> None:
        event_type = "tool_result" if event.status == "success" else "tool_error"
        with self.connection.transaction(), self.connection.cursor() as cursor:
            sequence = self._allocate_event_sequence(cursor, run_id=run_id)
            cursor.execute(
                """
                insert into corpus.agent_run_events (
                    run_id,
                    sequence,
                    occurred_at,
                    event_type,
                    status,
                    tool_name,
                    arguments,
                    result_char_count,
                    result_sha256,
                    result_excerpt,
                    error_type,
                    error_message,
                    payload
                )
                values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    sequence,
                    event.occurred_at,
                    event_type,
                    event.status,
                    event.tool_name,
                    _json(event.arguments),
                    event.result_char_count,
                    event.result_sha256,
                    event.result_excerpt,
                    event.error_type,
                    event.error_message,
                    _json({"source_trace_sequence": event.sequence, "stage": event.stage}),
                ),
            )

    def append_model_turn(self, *, run_id: UUID, event: ModelTurnUsage) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            sequence = self._allocate_event_sequence(cursor, run_id=run_id)
            cursor.execute(
                """
                insert into corpus.agent_run_events (
                    run_id,
                    sequence,
                    occurred_at,
                    event_type,
                    status,
                    payload
                )
                values (%s, %s, %s, 'model_turn', 'success', %s::jsonb)
                """,
                (
                    run_id,
                    sequence,
                    event.response_completed_at,
                    _json(event.as_dict()),
                ),
            )

    def complete_agent_run(
        self,
        *,
        run_id: UUID,
        usage: dict[str, object],
        trace_object_ref: str | None = None,
        result_object_ref: str | None = None,
    ) -> None:
        self._finish_agent_run(
            run_id=run_id,
            state="completed",
            usage=usage,
            trace_object_ref=trace_object_ref,
            result_object_ref=result_object_ref,
        )

    def fail_agent_run(
        self,
        *,
        run_id: UUID,
        state: AgentTerminalState,
        error_type: str,
        error_message: str,
        usage: dict[str, object],
        trace_object_ref: str | None = None,
    ) -> None:
        self._finish_agent_run(
            run_id=run_id,
            state=state,
            usage=usage,
            trace_object_ref=trace_object_ref,
            error_type=error_type,
            error_message=error_message,
        )

    def _finish_agent_run(
        self,
        *,
        run_id: UUID,
        state: AgentRunState,
        usage: dict[str, object],
        trace_object_ref: str | None = None,
        result_object_ref: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        request_count = _usage_int(usage, "request_count")
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        total_tokens = _usage_int(usage, "total_tokens")
        cache_hit = _usage_int(usage, "input_cache_hit_tokens")
        cache_miss = _usage_int(usage, "input_cache_miss_tokens")
        reasoning = _usage_int(usage, "reasoning_tokens")
        cost = _usage_cost(usage)
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.agent_runs
                set state = %s,
                    usage = %s::jsonb,
                    request_count = %s,
                    input_tokens = %s,
                    output_tokens = %s,
                    total_tokens = %s,
                    input_cache_hit_tokens = %s,
                    input_cache_miss_tokens = %s,
                    reasoning_tokens = %s,
                    estimated_cost_usd = %s,
                    trace_object_ref = coalesce(%s, trace_object_ref),
                    result_object_ref = coalesce(%s, result_object_ref),
                    error_type = %s,
                    error_message = %s,
                    finished_at = now(),
                    updated_at = now()
                where id = %s and state in ('pending', 'running')
                """,
                (
                    state,
                    _json(usage),
                    request_count,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cache_hit,
                    cache_miss,
                    reasoning,
                    cost,
                    trace_object_ref,
                    result_object_ref,
                    error_type,
                    error_message,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("agent run is missing or already terminal")

    def create_structure_pipeline_run(
        self,
        *,
        ingestion_job_id: UUID,
        artifact_id: UUID,
        idempotency_key: str,
    ) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.structure_pipeline_runs (
                    ingestion_job_id,
                    artifact_id,
                    idempotency_key,
                    state,
                    round_number
                )
                values (%s, %s, %s, 'structure_investigating', 0)
                on conflict (idempotency_key) do update
                set updated_at = now()
                returning id
                """,
                (ingestion_job_id, artifact_id, idempotency_key),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("structure pipeline upsert did not return an identifier")
            pipeline_run_id: UUID = row[0]
            return pipeline_run_id

    def record_structure_pipeline_usage(
        self,
        *,
        pipeline_run_id: UUID,
        usage: dict[str, object],
    ) -> None:
        request_count = _usage_int(usage, "request_count")
        total_tokens = _usage_int(usage, "total_tokens")
        cost = _usage_cost(usage)
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.structure_pipeline_runs
                set usage = %s::jsonb,
                    request_count = %s,
                    total_tokens = %s,
                    estimated_cost_usd = %s,
                    updated_at = now()
                where id = %s
                """,
                (_json(usage), request_count, total_tokens, cost, pipeline_run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"structure pipeline run {pipeline_run_id} does not exist")

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
    ) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                select state
                from corpus.structure_pipeline_runs
                where id = %s
                for update
                """,
                (pipeline_run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"structure pipeline run {pipeline_run_id} does not exist")
            current_state: StructurePipelineState = row[0]
            if target_state not in _ALLOWED_PIPELINE_TRANSITIONS[current_state]:
                raise InvalidPipelineTransition(
                    f"cannot transition structure pipeline from {current_state} to {target_state}"
                )

            terminal = target_state in {
                "structure_verified",
                "structure_rejected",
                "source_quality_blocked",
                "failed",
                "cancelled",
            }
            cursor.execute(
                """
                update corpus.structure_pipeline_runs
                set state = %s,
                    round_number = coalesce(%s, round_number),
                    structure_run_id = coalesce(%s, structure_run_id),
                    audit_run_id = coalesce(%s, audit_run_id),
                    page_map_object_ref = coalesce(%s, page_map_object_ref),
                    structure_result_object_ref = coalesce(%s, structure_result_object_ref),
                    audit_result_object_ref = coalesce(%s, audit_result_object_ref),
                    last_error_type = %s,
                    last_error_message = %s,
                    finished_at = case when %s then now() else null end,
                    updated_at = now()
                where id = %s
                """,
                (
                    target_state,
                    round_number,
                    structure_run_id,
                    audit_run_id,
                    page_map_object_ref,
                    structure_result_object_ref,
                    audit_result_object_ref,
                    error_type,
                    error_message,
                    terminal,
                    pipeline_run_id,
                ),
            )
