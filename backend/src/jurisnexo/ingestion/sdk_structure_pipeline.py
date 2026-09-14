from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from agents.models.interface import ModelProvider

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.sdk_structure_agent import (
    StructureAgentRunResult,
    StructureInvestigationBudgetExceeded,
    StructureInvestigationFailed,
    run_structure_agent,
)
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditorRunResult,
    run_structure_auditor,
)
from jurisnexo.ingestion.structure_run_ledger import AgentRunRole, StructureRunLedger
from jurisnexo.ingestion.structure_trace import ArtifactInspectionProfile, StructureToolTraceEvent
from jurisnexo.model_providers.agents_sdk_runtime_provider import (
    RuntimeSupervisingModelProvider,
)
from jurisnexo.model_providers.agents_sdk_usage_provider import UsageTrackingModelProvider
from jurisnexo.model_providers.usage_accounting import (
    ModelTurnUsage,
    ModelUsageSummary,
    ModelUsageTracker,
)

PersistedEventKind = Literal["tool", "model"]
PersistedEvent = StructureToolTraceEvent | ModelTurnUsage


@dataclass(frozen=True, slots=True)
class StructurePipelinePersistence:
    ledger: StructureRunLedger
    ingestion_job_id: UUID
    artifact_id: UUID
    idempotency_key: str
    provider: str


@dataclass(frozen=True, slots=True)
class StructurePipelineRound:
    round_number: int
    structure: StructureAgentRunResult
    audit: StructureAuditorRunResult
    structure_run_id: UUID | None = None
    audit_run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StructurePipelineRunResult:
    rounds: tuple[StructurePipelineRound, ...]
    usage_turns: tuple[ModelTurnUsage, ...] = ()
    usage_summary: ModelUsageSummary | None = None
    pipeline_run_id: UUID | None = None

    @property
    def structure(self) -> StructureAgentRunResult:
        return self.rounds[-1].structure

    @property
    def audit(self) -> StructureAuditorRunResult:
        return self.rounds[-1].audit

    @property
    def extraction_allowed(self) -> bool:
        return self.audit.audit.state == "APPROVED"

    @property
    def exhausted_reinvestigation(self) -> bool:
        return self.audit.audit.state in {
            "MORE_INVESTIGATION_REQUIRED",
            "APPROVED_WITH_AMENDMENTS",
        }


def _focused_audit_delta(previous: StructurePipelineRound) -> dict[str, object]:
    audit = previous.audit.audit
    return {
        "state": audit.state,
        "summary": audit.summary,
        "amendments": audit.amendments,
        "required_follow_up": audit.required_follow_up,
        "disputed_checks": [
            check.model_dump(mode="json")
            for check in audit.checks
            if check.status in {"contradicted", "unresolved"}
        ],
        "nonconfirmed_finding_reviews": [
            review.model_dump(mode="json")
            for review in audit.finding_reviews
            if review.action != "confirmed"
        ],
    }


def _focused_reinvestigation_context(
    *,
    previous: StructurePipelineRound,
    round_number: int,
) -> str:
    directives = [*previous.audit.audit.required_follow_up, *previous.audit.audit.amendments]
    rendered_directives = (
        "\n".join(f"- {item}" for item in directives) or "- Resolve the material audit objection."
    )
    audit_delta = json.dumps(
        _focused_audit_delta(previous),
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"This is focused structure reinvestigation round {round_number}. The prior candidate is "
        "working state, not authority. Preserve source-backed parts that were not challenged; "
        "change only what evidence or the audit requires.\n\n"
        "Prior candidate hypothesis:\n"
        f"{previous.structure.hypothesis.model_dump_json(indent=2)}\n\n"
        "Material audit delta (supported checks intentionally omitted to reduce noise):\n"
        f"{audit_delta}\n\n"
        "Questions that must be resolved before finalization:\n"
        f"{rendered_directives}\n\n"
        "Use source tools only where they can change one of those questions or reveal a material "
        "regression. Do not re-prove unchanged structure for coverage. Preserve correct findings, "
        "replace incorrect ones with source-backed findings, and keep genuine uncertainty explicit."
    )


def _eligible_carry_forward_finding_ids(
    *,
    previous: StructurePipelineRound,
    current: DocumentStructureHypothesis,
) -> tuple[str, ...]:
    """Return previously confirmed findings whose complete candidate payload is unchanged."""

    confirmed = {
        review.finding_id
        for review in previous.audit.audit.finding_reviews
        if review.action == "confirmed" and review.finding_id is not None
    }
    prior_by_id = {
        finding.finding_id: finding.model_dump(mode="json")
        for finding in previous.structure.hypothesis.structure_findings
    }
    current_by_id = {
        finding.finding_id: finding.model_dump(mode="json")
        for finding in current.structure_findings
    }
    eligible = [
        finding_id
        for finding_id in confirmed
        if finding_id in prior_by_id
        and finding_id in current_by_id
        and prior_by_id[finding_id] == current_by_id[finding_id]
    ]
    return tuple(sorted(eligible))


def _tool_budget(
    *,
    max_turns: int,
    max_runtime_seconds: int,
    max_tool_output_chars: int,
    max_total_tool_result_chars: int,
    max_identical_tool_calls: int,
    search_max_hits: int,
) -> dict[str, int]:
    return {
        "max_turns": max_turns,
        "max_runtime_seconds": max_runtime_seconds,
        "max_tool_output_chars": max_tool_output_chars,
        "max_total_tool_result_chars": max_total_tool_result_chars,
        "max_identical_tool_calls": max_identical_tool_calls,
        "search_max_hits": search_max_hits,
    }


def _persist_events(
    *,
    ledger: StructureRunLedger,
    run_id: UUID,
    tool_trace: tuple[StructureToolTraceEvent, ...],
    model_turns: tuple[ModelTurnUsage, ...],
) -> None:
    combined: list[tuple[datetime, PersistedEventKind, PersistedEvent]] = []
    combined.extend((event.occurred_at, "tool", event) for event in tool_trace)
    combined.extend((event.response_completed_at, "model", event) for event in model_turns)
    combined.sort(key=lambda item: item[0])
    for _occurred_at, kind, event in combined:
        if kind == "tool":
            assert isinstance(event, StructureToolTraceEvent)
            ledger.append_trace_event(run_id=run_id, event=event)
        else:
            assert isinstance(event, ModelTurnUsage)
            ledger.append_model_turn(run_id=run_id, event=event)


def _stage_turns(
    tracker: ModelUsageTracker | None,
    start_index: int,
) -> tuple[ModelTurnUsage, ...]:
    if tracker is None:
        return ()
    return tuple(tracker.turns[start_index:])


def _usage_dict(
    tracker: ModelUsageTracker | None,
    turns: tuple[ModelTurnUsage, ...],
) -> dict[str, object]:
    if tracker is None:
        return {
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "input_cache_hit_tokens": 0,
            "input_cache_miss_tokens": 0,
            "reasoning_tokens": 0,
            "estimated_cost_usd": None,
        }
    return tracker.summary(turns).as_dict()


def _session_usage_dict(tracker: ModelUsageTracker | None) -> dict[str, object]:
    return _usage_dict(tracker, tuple(tracker.turns) if tracker is not None else ())


def _create_agent_run(
    *,
    persistence: StructurePipelinePersistence | None,
    role: AgentRunRole,
    round_number: int,
    model: str,
    budget: dict[str, int],
    parent_run_id: UUID | None,
) -> UUID | None:
    if persistence is None:
        return None
    return persistence.ledger.create_agent_run(
        ingestion_job_id=persistence.ingestion_job_id,
        artifact_id=persistence.artifact_id,
        role=role,
        round_number=round_number,
        provider=persistence.provider,
        model=model,
        prompt_sha256=None,
        tool_budget=budget,
        parent_run_id=parent_run_id,
    )


def _finish_successful_run(
    *,
    persistence: StructurePipelinePersistence | None,
    run_id: UUID | None,
    tool_trace: tuple[StructureToolTraceEvent, ...],
    model_turns: tuple[ModelTurnUsage, ...],
    tracker: ModelUsageTracker | None,
) -> None:
    if persistence is None or run_id is None:
        return
    _persist_events(
        ledger=persistence.ledger,
        run_id=run_id,
        tool_trace=tool_trace,
        model_turns=model_turns,
    )
    persistence.ledger.complete_agent_run(
        run_id=run_id,
        usage=_usage_dict(tracker, model_turns),
    )


def _finish_failed_run(
    *,
    persistence: StructurePipelinePersistence | None,
    pipeline_run_id: UUID | None,
    run_id: UUID | None,
    tool_trace: tuple[StructureToolTraceEvent, ...],
    model_turns: tuple[ModelTurnUsage, ...],
    tracker: ModelUsageTracker | None,
    exc: StructureInvestigationBudgetExceeded | StructureInvestigationFailed,
) -> None:
    if persistence is None or pipeline_run_id is None or run_id is None:
        return
    _persist_events(
        ledger=persistence.ledger,
        run_id=run_id,
        tool_trace=tool_trace,
        model_turns=model_turns,
    )
    budget_exhausted = isinstance(exc, StructureInvestigationBudgetExceeded)
    error_type = type(exc).__name__ if budget_exhausted else exc.error_type
    error_message = str(exc)
    persistence.ledger.fail_agent_run(
        run_id=run_id,
        state="budget_exhausted" if budget_exhausted else "failed",
        error_type=error_type,
        error_message=error_message,
        usage=_usage_dict(tracker, model_turns),
    )
    persistence.ledger.record_structure_pipeline_usage(
        pipeline_run_id=pipeline_run_id,
        usage=_session_usage_dict(tracker),
    )
    persistence.ledger.transition_structure_pipeline(
        pipeline_run_id=pipeline_run_id,
        target_state="failed",
        error_type=error_type,
        error_message=error_message,
    )


async def run_structure_pipeline(
    *,
    environment: DocumentEnvironment,
    artifact_label: str,
    model: str,
    structure_max_turns: int = 128,
    structure_max_runtime_seconds: int = 600,
    audit_max_turns: int = 96,
    audit_max_runtime_seconds: int = 600,
    max_reinvestigation_rounds: int = 2,
    max_tool_output_chars: int = 60_000,
    max_total_tool_result_chars: int = 750_000,
    max_identical_tool_calls: int = 4,
    search_max_hits: int = 20,
    artifact_profile: ArtifactInspectionProfile | None = None,
    model_provider: ModelProvider | None = None,
    usage_tracker: ModelUsageTracker | None = None,
    persistence: StructurePipelinePersistence | None = None,
    trace_journal_path: Path | None = None,
) -> StructurePipelineRunResult:
    """Run discovery, adversarial audit, focused reinvestigation, and durable checkpoints."""

    if max_reinvestigation_rounds < 0 or max_reinvestigation_rounds > 5:
        raise ValueError("max_reinvestigation_rounds must be between 0 and 5")
    if persistence is not None and usage_tracker is None:
        raise ValueError("durable structure persistence requires a model usage tracker")

    effective_provider: ModelProvider | None = model_provider
    usage_provider: UsageTrackingModelProvider | None = None
    runtime_provider: RuntimeSupervisingModelProvider | None = None
    if model_provider is not None and usage_tracker is not None:
        usage_provider = UsageTrackingModelProvider(inner=model_provider, tracker=usage_tracker)
        effective_provider = usage_provider
    if effective_provider is not None:
        runtime_provider = RuntimeSupervisingModelProvider(inner=effective_provider)
        effective_provider = runtime_provider

    pipeline_run_id = (
        persistence.ledger.create_structure_pipeline_run(
            ingestion_job_id=persistence.ingestion_job_id,
            artifact_id=persistence.artifact_id,
            idempotency_key=persistence.idempotency_key,
        )
        if persistence is not None
        else None
    )
    rounds: list[StructurePipelineRound] = []
    parent_run_id: UUID | None = None

    structure_budget = _tool_budget(
        max_turns=structure_max_turns,
        max_runtime_seconds=structure_max_runtime_seconds,
        max_tool_output_chars=max_tool_output_chars,
        max_total_tool_result_chars=max_total_tool_result_chars,
        max_identical_tool_calls=max_identical_tool_calls,
        search_max_hits=search_max_hits,
    )
    audit_budget = _tool_budget(
        max_turns=audit_max_turns,
        max_runtime_seconds=audit_max_runtime_seconds,
        max_tool_output_chars=max_tool_output_chars,
        max_total_tool_result_chars=max_total_tool_result_chars,
        max_identical_tool_calls=max_identical_tool_calls,
        search_max_hits=search_max_hits,
    )

    for round_number in range(0, max_reinvestigation_rounds + 1):
        if round_number > 0:
            previous = rounds[-1]
            if previous.audit.audit.state not in {
                "MORE_INVESTIGATION_REQUIRED",
                "APPROVED_WITH_AMENDMENTS",
            }:
                break
            investigation_context = _focused_reinvestigation_context(
                previous=previous,
                round_number=round_number,
            )
            role: AgentRunRole = "structure_reinvestigation"
            trace_stage = "structure_reinvestigation"
        else:
            investigation_context = None
            role = "structure_agent"
            trace_stage = "structure_agent"

        structure_run_id = _create_agent_run(
            persistence=persistence,
            role=role,
            round_number=round_number,
            model=model,
            budget=structure_budget,
            parent_run_id=parent_run_id,
        )
        turn_start = len(usage_tracker.turns) if usage_tracker is not None else 0
        if usage_provider is not None:
            usage_provider.set_scope(role=role, round_number=round_number)
        if runtime_provider is not None:
            runtime_provider.set_scope(
                role=role,
                round_number=round_number,
                runtime_budget_seconds=structure_max_runtime_seconds,
            )
        try:
            structure = await run_structure_agent(
                environment=environment,
                artifact_label=artifact_label,
                model=model,
                max_turns=structure_max_turns,
                max_runtime_seconds=structure_max_runtime_seconds,
                max_tool_output_chars=max_tool_output_chars,
                max_total_tool_result_chars=max_total_tool_result_chars,
                max_identical_tool_calls=max_identical_tool_calls,
                search_max_hits=search_max_hits,
                artifact_profile=artifact_profile,
                model_provider=effective_provider,
                trace_journal_path=trace_journal_path,
                trace_stage=trace_stage,
                investigation_context=investigation_context,
            )
        except (StructureInvestigationBudgetExceeded, StructureInvestigationFailed) as exc:
            _finish_failed_run(
                persistence=persistence,
                pipeline_run_id=pipeline_run_id,
                run_id=structure_run_id,
                tool_trace=exc.tool_trace,
                model_turns=_stage_turns(usage_tracker, turn_start),
                tracker=usage_tracker,
                exc=exc,
            )
            raise

        structure_turns = _stage_turns(usage_tracker, turn_start)
        _finish_successful_run(
            persistence=persistence,
            run_id=structure_run_id,
            tool_trace=structure.tool_trace,
            model_turns=structure_turns,
            tracker=usage_tracker,
        )
        if persistence is not None and pipeline_run_id is not None:
            persistence.ledger.record_structure_pipeline_usage(
                pipeline_run_id=pipeline_run_id,
                usage=_session_usage_dict(usage_tracker),
            )
            persistence.ledger.transition_structure_pipeline(
                pipeline_run_id=pipeline_run_id,
                target_state="structure_candidate",
                round_number=round_number,
                structure_run_id=structure_run_id,
            )
            persistence.ledger.transition_structure_pipeline(
                pipeline_run_id=pipeline_run_id,
                target_state="structure_auditing",
                round_number=round_number,
                structure_run_id=structure_run_id,
            )

        audit_run_id = _create_agent_run(
            persistence=persistence,
            role="structure_auditor",
            round_number=round_number,
            model=model,
            budget=audit_budget,
            parent_run_id=structure_run_id,
        )
        turn_start = len(usage_tracker.turns) if usage_tracker is not None else 0
        if usage_provider is not None:
            usage_provider.set_scope(role="structure_auditor", round_number=round_number)
        if runtime_provider is not None:
            runtime_provider.set_scope(
                role="structure_auditor",
                round_number=round_number,
                runtime_budget_seconds=audit_max_runtime_seconds,
            )

        prior_round = rounds[-1] if rounds else None
        prior_audit = prior_round.audit.audit if prior_round is not None else None
        carry_forward_finding_ids = (
            _eligible_carry_forward_finding_ids(
                previous=prior_round,
                current=structure.hypothesis,
            )
            if prior_round is not None
            else ()
        )
        try:
            audit = await run_structure_auditor(
                environment=environment,
                hypothesis=structure.hypothesis,
                artifact_label=artifact_label,
                model=model,
                structure_agent_trace=structure.tool_trace,
                prior_audit=prior_audit,
                carry_forward_finding_ids=carry_forward_finding_ids,
                max_turns=audit_max_turns,
                max_runtime_seconds=audit_max_runtime_seconds,
                max_tool_output_chars=max_tool_output_chars,
                max_total_tool_result_chars=max_total_tool_result_chars,
                max_identical_tool_calls=max_identical_tool_calls,
                search_max_hits=search_max_hits,
                artifact_profile=artifact_profile,
                model_provider=effective_provider,
                trace_journal_path=trace_journal_path,
            )
        except (StructureInvestigationBudgetExceeded, StructureInvestigationFailed) as exc:
            _finish_failed_run(
                persistence=persistence,
                pipeline_run_id=pipeline_run_id,
                run_id=audit_run_id,
                tool_trace=exc.tool_trace,
                model_turns=_stage_turns(usage_tracker, turn_start),
                tracker=usage_tracker,
                exc=exc,
            )
            raise

        audit_turns = _stage_turns(usage_tracker, turn_start)
        _finish_successful_run(
            persistence=persistence,
            run_id=audit_run_id,
            tool_trace=audit.tool_trace,
            model_turns=audit_turns,
            tracker=usage_tracker,
        )
        completed_round = StructurePipelineRound(
            round_number=round_number,
            structure=structure,
            audit=audit,
            structure_run_id=structure_run_id,
            audit_run_id=audit_run_id,
        )
        rounds.append(completed_round)
        parent_run_id = audit_run_id

        if persistence is not None and pipeline_run_id is not None:
            persistence.ledger.record_structure_pipeline_usage(
                pipeline_run_id=pipeline_run_id,
                usage=_session_usage_dict(usage_tracker),
            )
            state = audit.audit.state
            if state == "APPROVED":
                target = "structure_verified"
            elif state == "REJECTED":
                target = "structure_rejected"
            elif state == "SOURCE_QUALITY_BLOCKED":
                target = "source_quality_blocked"
            elif round_number < max_reinvestigation_rounds:
                target = "structure_reinvestigating"
            else:
                target = "source_quality_blocked"
            persistence.ledger.transition_structure_pipeline(
                pipeline_run_id=pipeline_run_id,
                target_state=target,
                round_number=round_number,
                structure_run_id=structure_run_id,
                audit_run_id=audit_run_id,
            )

        if audit.audit.state not in {
            "MORE_INVESTIGATION_REQUIRED",
            "APPROVED_WITH_AMENDMENTS",
        }:
            break

    if not rounds:
        raise RuntimeError("structure pipeline completed without a structure/audit round")
    summary = usage_tracker.summary() if usage_tracker is not None else None
    return StructurePipelineRunResult(
        rounds=tuple(rounds),
        usage_turns=tuple(usage_tracker.turns) if usage_tracker is not None else (),
        usage_summary=summary,
        pipeline_run_id=pipeline_run_id,
    )
