from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agents.models.interface import ModelProvider

from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.sdk_structure_agent import (
    StructureAgentRunResult,
    run_structure_agent,
)
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditorRunResult,
    run_structure_auditor,
)
from jurisnexo.ingestion.structure_trace import ArtifactInspectionProfile


@dataclass(frozen=True, slots=True)
class StructurePipelineRound:
    round_number: int
    structure: StructureAgentRunResult
    audit: StructureAuditorRunResult


@dataclass(frozen=True, slots=True)
class StructurePipelineRunResult:
    rounds: tuple[StructurePipelineRound, ...]

    @property
    def structure(self) -> StructureAgentRunResult:
        return self.rounds[-1].structure

    @property
    def audit(self) -> StructureAuditorRunResult:
        return self.rounds[-1].audit

    @property
    def extraction_allowed(self) -> bool:
        # Amendments are not applied magically. Only a clean re-audit can unlock extraction.
        return self.audit.audit.state == "APPROVED"

    @property
    def exhausted_reinvestigation(self) -> bool:
        return self.audit.audit.state in {
            "MORE_INVESTIGATION_REQUIRED",
            "APPROVED_WITH_AMENDMENTS",
        }


def _focused_reinvestigation_context(
    *,
    previous: StructurePipelineRound,
    round_number: int,
) -> str:
    follow_up = previous.audit.audit.required_follow_up
    amendments = previous.audit.audit.amendments
    directives = [*follow_up, *amendments]
    rendered_directives = (
        "\n".join(f"- {item}" for item in directives)
        or "- Re-check audit findings."
    )
    return (
        f"This is bounded structure reinvestigation round {round_number}. The prior candidate is "
        "not authoritative and must be revised only where source evidence supports revision.\n\n"
        "Prior candidate hypothesis:\n"
        f"{previous.structure.hypothesis.model_dump_json(indent=2)}\n\n"
        "Prior adversarial audit:\n"
        f"{previous.audit.audit.model_dump_json(indent=2)}\n\n"
        "Focused checks that must be resolved before finalization:\n"
        f"{rendered_directives}\n\n"
        "Use the document tools to resolve these checks. Preserve correct prior findings, replace "
        "incorrect ones with source-backed findings, and keep unresolved uncertainty explicit."
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
    trace_journal_path: Path | None = None,
) -> StructurePipelineRunResult:
    """Run structure discovery, adversarial audit, and bounded focused reinvestigation."""

    if max_reinvestigation_rounds < 0 or max_reinvestigation_rounds > 5:
        raise ValueError("max_reinvestigation_rounds must be between 0 and 5")

    rounds: list[StructurePipelineRound] = []
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
        model_provider=model_provider,
        trace_journal_path=trace_journal_path,
    )
    audit = await run_structure_auditor(
        environment=environment,
        hypothesis=structure.hypothesis,
        artifact_label=artifact_label,
        model=model,
        structure_agent_trace=structure.tool_trace,
        max_turns=audit_max_turns,
        max_runtime_seconds=audit_max_runtime_seconds,
        max_tool_output_chars=max_tool_output_chars,
        max_total_tool_result_chars=max_total_tool_result_chars,
        max_identical_tool_calls=max_identical_tool_calls,
        search_max_hits=search_max_hits,
        artifact_profile=artifact_profile,
        model_provider=model_provider,
        trace_journal_path=trace_journal_path,
    )
    rounds.append(StructurePipelineRound(round_number=0, structure=structure, audit=audit))

    for round_number in range(1, max_reinvestigation_rounds + 1):
        previous = rounds[-1]
        if previous.audit.audit.state not in {
            "MORE_INVESTIGATION_REQUIRED",
            "APPROVED_WITH_AMENDMENTS",
        }:
            break

        focused_context = _focused_reinvestigation_context(
            previous=previous,
            round_number=round_number,
        )
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
            model_provider=model_provider,
            trace_journal_path=trace_journal_path,
            trace_stage="structure_reinvestigation",
            investigation_context=focused_context,
        )
        combined_prior_trace = tuple(
            event
            for completed_round in rounds
            for event in completed_round.structure.tool_trace
        ) + structure.tool_trace
        audit = await run_structure_auditor(
            environment=environment,
            hypothesis=structure.hypothesis,
            artifact_label=artifact_label,
            model=model,
            structure_agent_trace=combined_prior_trace,
            max_turns=audit_max_turns,
            max_runtime_seconds=audit_max_runtime_seconds,
            max_tool_output_chars=max_tool_output_chars,
            max_total_tool_result_chars=max_total_tool_result_chars,
            max_identical_tool_calls=max_identical_tool_calls,
            search_max_hits=search_max_hits,
            artifact_profile=artifact_profile,
            model_provider=model_provider,
            trace_journal_path=trace_journal_path,
        )
        rounds.append(
            StructurePipelineRound(
                round_number=round_number,
                structure=structure,
                audit=audit,
            )
        )

    return StructurePipelineRunResult(rounds=tuple(rounds))