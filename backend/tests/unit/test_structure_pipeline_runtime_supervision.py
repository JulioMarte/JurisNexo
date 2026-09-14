from __future__ import annotations

import asyncio
from typing import cast

import pytest
from agents.models.interface import ModelProvider

from jurisnexo.ingestion import sdk_structure_pipeline as pipeline_module
from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.sdk_structure_agent import StructureAgentRunResult
from jurisnexo.ingestion.sdk_structure_auditor import (
    StructureAuditorRunResult,
    StructureAuditResult,
)
from jurisnexo.ingestion.sdk_structure_pipeline import run_structure_pipeline

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _structure() -> StructureAgentRunResult:
    hypothesis = DocumentStructureHypothesis.model_validate(
        {
            "artifact_class": "bulletin",
            "family_name_candidate": "synthetic",
            "structure_confidence": 0.9,
            "has_index": True,
            "index_page_candidates": [1],
            "status": "candidate",
        }
    )
    return StructureAgentRunResult(
        hypothesis=hypothesis,
        usage_total_tokens=0,
        last_agent_name="structure",
        tool_trace=(),
    )


def _audit() -> StructureAuditorRunResult:
    audit = StructureAuditResult.model_validate(
        {
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
    )
    return StructureAuditorRunResult(
        audit=audit,
        usage_total_tokens=0,
        last_agent_name="auditor",
        tool_trace=(),
    )


def test_pipeline_supervises_runtime_without_usage_tracker_and_uses_stage_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes: list[tuple[str, int, float]] = []
    providers_seen: list[object] = []

    class RecordingRuntimeProvider:
        def __init__(self, *, inner: ModelProvider) -> None:
            self.inner = inner

        def set_scope(
            self,
            *,
            role: str,
            round_number: int,
            runtime_budget_seconds: float,
            soft_deadline_fraction: float = 0.80,
        ) -> None:
            del soft_deadline_fraction
            scopes.append((role, round_number, runtime_budget_seconds))

    async def fake_structure_agent(**kwargs: object) -> StructureAgentRunResult:
        providers_seen.append(kwargs["model_provider"])
        return _structure()

    async def fake_structure_auditor(**kwargs: object) -> StructureAuditorRunResult:
        providers_seen.append(kwargs["model_provider"])
        return _audit()

    monkeypatch.setattr(
        pipeline_module,
        "RuntimeSupervisingModelProvider",
        RecordingRuntimeProvider,
    )
    monkeypatch.setattr(pipeline_module, "run_structure_agent", fake_structure_agent)
    monkeypatch.setattr(pipeline_module, "run_structure_auditor", fake_structure_auditor)

    raw_provider = cast(ModelProvider, object())
    result = asyncio.run(
        run_structure_pipeline(
            environment=DocumentEnvironment(("page one",)),
            artifact_label="synthetic bulletin",
            model="fake-model",
            structure_max_runtime_seconds=321,
            audit_max_runtime_seconds=123,
            model_provider=raw_provider,
            usage_tracker=None,
        )
    )

    assert result.extraction_allowed is True
    assert len(providers_seen) == 2
    assert all(isinstance(provider, RecordingRuntimeProvider) for provider in providers_seen)
    assert scopes == [
        ("structure_agent", 0, 321),
        ("structure_auditor", 0, 123),
    ]
