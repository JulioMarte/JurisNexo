from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.ingestion.agentic_document_discovery import (
    DiscoveryBudget,
    run_agentic_document_discovery,
)
from jurisnexo.ingestion.context_governor import ContextPolicy
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelUsage,
    StructuredGenerationResult,
)

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class ScriptedProvider:
    responses: tuple[JsonObject, ...]
    prompts: list[str] = field(default_factory=list)
    schemas: list[JsonObject] = field(default_factory=list)
    cursor: int = 0

    @property
    def provider_name(self) -> str:
        return "scripted"

    @property
    def model_name(self) -> str:
        return "scripted-model"

    def count_input_tokens(self, text: str) -> int:
        return len(text)

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        del max_output_tokens, thinking_level
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
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


def _tool_enum(schema: JsonObject) -> list[str]:
    properties = schema["properties"]
    assert isinstance(properties, dict)
    tool = properties["tool"]
    assert isinstance(tool, dict)
    values = tool["enum"]
    assert isinstance(values, list)
    return [value for value in values if isinstance(value, str)]


def _candidate_hypothesis() -> JsonObject:
    return {
        "artifact_class": "bulletin",
        "family_name_candidate": "legacy_bulletin_candidate",
        "structure_confidence": 0.8,
        "has_index": True,
        "index_page_candidates": [1],
        "candidate_segments": [],
        "segmentation_hypotheses": [],
        "metadata_hypotheses": [],
        "anomalies": [],
        "recommended_next_actions": [],
        "status": "candidate",
    }


def test_agent_searches_then_inspects_then_synthesizes() -> None:
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "search_text",
                "rationale": "Find repeated decision headings.",
                "query": "SENTENCIA DEL",
            },
            {"tool": "get_page", "rationale": "Inspect hit.", "page_number": 4},
            {"tool": "finish", "rationale": "Enough evidence."},
            _candidate_hypothesis(),
        )
    )
    environment = DocumentEnvironment(
        ("INDICE", "Introducción", "Texto", "SENTENCIA DEL 4 DE MARZO DE 1974")
    )
    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label="Boletin 1974",
        budget=DiscoveryBudget(max_model_calls=5, max_total_tokens=500),
    )
    assert [step.decision.tool for step in result.steps] == ["search_text", "get_page"]
    assert result.usage.total_tokens == 80
    assert "get_printed_page" not in provider.prompts[0]
    assert "delegate_printed_pages" not in _tool_enum(provider.schemas[0])


def test_agent_exposes_printed_navigation_and_delegation_only_when_supported() -> None:
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "get_printed_page",
                "rationale": "Follow index target.",
                "printed_page_number": 183,
            },
            {"tool": "finish", "rationale": "Confirmed."},
            _candidate_hypothesis(),
        )
    )
    environment = DocumentEnvironment(
        ("SUMARIO", "SENTENCIA"),
        printed_page_numbers=(None, 183),
        source_references=("physical_pages=3", "physical_pages=5,6; side=right"),
    )
    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label="Boletin Judicial 831",
        budget=DiscoveryBudget(max_model_calls=4, max_total_tokens=500),
    )
    assert "physical_pages=5,6; side=right" in result.steps[0].tool_output
    tools = _tool_enum(provider.schemas[0])
    assert "get_printed_pages" in tools
    assert "delegate_printed_pages" in tools


def test_large_range_preflight_then_delegates_to_fresh_locator() -> None:
    hypothesis = _candidate_hypothesis()
    hypothesis["index_reference_investigations"] = [
        {
            "reference_as_printed": 353,
            "expected_description": "Pelayo Fernández decision",
            "resolution_status": "confirmed_nearby",
            "observed_decision_start_printed_page": 354,
            "evidence_printed_pages": [353, 354],
            "evidence_view_pages": [2, 3],
            "observed_description": "Expected heading starts on 354",
            "explanation": (
                "353 continues the prior matter; 354 starts the expected decision."
            ),
            "confidence": 0.93,
        }
    ]
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "get_printed_page",
                "rationale": "Inspect the indexed reference first.",
                "printed_page_number": 353,
            },
            {
                "tool": "get_printed_pages",
                "rationale": "Inspect a broad neighborhood.",
                "start_printed_page_number": 352,
                "end_printed_page_number": 355,
            },
            {
                "tool": "delegate_printed_pages",
                "rationale": "The preflight says the parent should not inline the range.",
                "start_printed_page_number": 352,
                "end_printed_page_number": 355,
                "expected_description": "Pelayo Fernández decision",
            },
            {
                "candidate_found": True,
                "candidate_start_printed_page": 354,
                "evidence_printed_pages": [354],
                "observed_description": "SENTENCIA heading with Pelayo Fernández",
                "explanation": "The expected decision starts here.",
                "confidence": 0.96,
            },
            {
                "tool": "finish",
                "rationale": "Delegated evidence resolves the discrepancy.",
            },
            hypothesis,
        )
    )
    environment = DocumentEnvironment(
        (
            "prior ending " * 20,
            "continuation " * 20,
            "SENTENCIA DE FECHA 20 DE FEBRERO DEL 1980 Pelayo Fernández " * 20,
            "continuation of Pelayo " * 20,
        ),
        printed_page_numbers=(352, 353, 354, 355),
        source_references=(
            "physical_pages=173,174; side=left",
            "physical_pages=173,174; side=right",
            "physical_pages=175,176; side=left",
            "physical_pages=175,176; side=right",
        ),
    )
    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label="Boletin Judicial 831",
        budget=DiscoveryBudget(
            max_model_calls=6,
            max_total_tokens=1_000,
            context_policy=ContextPolicy(
                parent_soft_limit_tokens=2_500,
                delegated_soft_limit_tokens=20_000,
            ),
        ),
    )
    assert [step.decision.tool for step in result.steps] == [
        "get_printed_page",
        "get_printed_pages",
        "delegate_printed_pages",
    ]
    assert "CONTEXT PREFLIGHT - RANGE NOT INLINED" in result.steps[1].tool_output
    assert "requested_evidence_tokens=" in result.steps[1].tool_output
    assert "DELEGATED DECISION LOCATOR RESULT" in result.steps[2].tool_output
    assert "PRINTED PAGE 354" in result.steps[2].tool_output
    assert "physical_pages=175,176; side=left" in result.steps[2].tool_output
    assert len(result.steps[2].delegated_model_results) == 1
    investigation = result.hypothesis.index_reference_investigations[0]
    assert investigation.observed_decision_start_printed_page == 354


def test_locator_rejects_evidence_it_never_received() -> None:
    provider = ScriptedProvider(
        responses=(
            {
                "tool": "delegate_printed_pages",
                "rationale": "Locate expected decision.",
                "start_printed_page_number": 352,
                "end_printed_page_number": 355,
                "expected_description": "Pelayo Fernández decision",
            },
            {
                "candidate_found": True,
                "candidate_start_printed_page": 999,
                "evidence_printed_pages": [999],
                "observed_description": "invented",
                "explanation": "invented",
                "confidence": 0.99,
            },
        )
    )
    environment = DocumentEnvironment(
        ("a", "b", "c", "d"),
        printed_page_numbers=(352, 353, 354, 355),
    )
    with pytest.raises(ValueError, match="outside its inspected chunk"):
        run_agentic_document_discovery(
            provider=provider,
            environment=environment,
            artifact_label="Boletin Judicial 831",
            budget=DiscoveryBudget(
                max_model_calls=3,
                max_total_tokens=500,
                context_policy=ContextPolicy(delegated_soft_limit_tokens=20_000),
            ),
        )


def test_exact_duplicate_tool_call_is_not_reexecuted() -> None:
    provider = ScriptedProvider(
        responses=(
            {"tool": "get_page", "rationale": "Inspect.", "page_number": 1},
            {"tool": "get_page", "rationale": "Inspect again.", "page_number": 1},
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
                "recommended_next_actions": [],
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
