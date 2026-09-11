from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.ingestion.agentic_document_discovery import (
    DiscoveryBudget,
    run_agentic_document_discovery,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelUsage,
    StructuredGenerationResult,
)

pytestmark = pytest.mark.unit


def _empty_prompts() -> list[str]:
    return []


@dataclass(slots=True)
class ScriptedProvider:
    responses: tuple[JsonObject, ...]
    prompts: list[str] = field(default_factory=_empty_prompts)
    cursor: int = 0

    @property
    def provider_name(self) -> str:
        return "scripted"

    @property
    def model_name(self) -> str:
        return "scripted-model"

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        del json_schema, max_output_tokens, thinking_level
        self.prompts.append(prompt)
        response = self.responses[self.cursor]
        self.cursor += 1
        return StructuredGenerationResult(
            value=response,
            provider=self.provider_name,
            model=self.model_name,
            model_version="test",
            response_id=f"response-{self.cursor}",
            usage=ModelUsage(
                input_tokens=10,
                output_tokens=5,
                thinking_tokens=5,
                total_tokens=20,
            ),
        )


def _candidate_hypothesis() -> JsonObject:
    return {
        "artifact_class": "bulletin",
        "family_name_candidate": "legacy_bulletin_candidate",
        "structure_confidence": 0.8,
        "has_index": True,
        "index_page_candidates": [1],
        "candidate_segments": [],
        "segmentation_hypotheses": [
            {
                "description": "Decision starts use SENTENCIA DEL date headings.",
                "evidence": ["printed page 183"],
                "confidence": 0.85,
            }
        ],
        "metadata_hypotheses": [],
        "anomalies": ["Only one candidate start was inspected directly."],
        "recommended_next_actions": [
            "Validate all index targets before accepting the family."
        ],
        "status": "candidate",
    }


def test_agent_searches_then_inspects_then_synthesizes() -> None:
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "search_text",
                "rationale": "Find repeated decision headings before reading many pages.",
                "query": "SENTENCIA DEL",
            },
            {
                "tool": "get_page",
                "rationale": "Inspect one search hit for the local heading grammar.",
                "page_number": 4,
            },
            {
                "tool": "finish",
                "rationale": (
                    "The index and repeated heading provide enough evidence for a candidate."
                ),
            },
            _candidate_hypothesis(),
        )
    )
    environment = DocumentEnvironment(
        (
            "INDICE\nSentencia A .... página 4",
            "Introducción",
            "Texto preliminar",
            "SENTENCIA DEL 4 DE MARZO DE 1974\nExpediente núm. 1234",
            "Continuación",
            "SENTENCIA DEL 11 DE MARZO DE 1974\nExpediente núm. 1277",
        )
    )

    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label="Boletin 1974",
        budget=DiscoveryBudget(max_model_calls=5, max_total_tokens=500),
    )

    assert [step.decision.tool for step in result.steps] == ["search_text", "get_page"]
    assert "view_page=4" in result.steps[0].tool_output
    assert "VIEW PAGE 4" in result.steps[1].tool_output
    assert result.hypothesis.artifact_class == "bulletin"
    assert result.usage.total_tokens == 80
    assert len(provider.prompts) == 4
    assert "untrusted data" in provider.prompts[0]
    assert "get_printed_page" not in provider.prompts[0]


def test_agent_can_follow_resolved_printed_page_reference_with_provenance() -> None:
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "get_printed_page",
                "rationale": "The index points to printed page 183.",
                "printed_page_number": 183,
            },
            {"tool": "finish", "rationale": "The target page confirms the heading."},
            _candidate_hypothesis(),
        )
    )
    environment = DocumentEnvironment(
        (
            "SUMARIO\nMateria Correccional .... Pág. 183",
            "SENTENCIA DE FECHA 6 DE FEBRERO DEL 1980\nMateria: Correccional",
        ),
        printed_page_numbers=(None, 183),
        source_references=("physical_pages=3", "physical_pages=5,6; side=right"),
    )

    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label="Boletin Judicial 831",
        budget=DiscoveryBudget(max_model_calls=4, max_total_tokens=500),
    )

    assert [step.decision.tool for step in result.steps] == ["get_printed_page"]
    output = result.steps[0].tool_output
    assert "PRINTED PAGE 183" in output
    assert "physical_pages=5,6; side=right" in output
    assert "get_printed_page" in provider.prompts[0]
    assert "resolved_printed_pages=1" in provider.prompts[0]


def test_exact_duplicate_tool_call_is_not_reexecuted() -> None:
    provider = ScriptedProvider(
        responses=(
            {"tool": "get_page", "rationale": "Inspect page.", "page_number": 1},
            {"tool": "get_page", "rationale": "Inspect page again.", "page_number": 1},
            {"tool": "finish", "rationale": "Stop."},
            {
                "artifact_class": "unknown",
                "family_name_candidate": "unknown",
                "structure_confidence": 0.2,
                "has_index": False,
                "index_page_candidates": [],
                "candidate_segments": [],
                "segmentation_hypotheses": [],
                "metadata_hypotheses": [],
                "anomalies": ["Insufficient evidence"],
                "recommended_next_actions": ["Inspect a larger artifact sample"],
                "status": "insufficient_structure_confidence",
            },
        )
    )

    result = run_agentic_document_discovery(
        provider=provider,
        environment=DocumentEnvironment(("Only page",)),
        artifact_label="unknown",
        budget=DiscoveryBudget(max_model_calls=5, max_total_tokens=500),
    )

    assert "already executed" in result.steps[1].tool_output
