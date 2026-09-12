from __future__ import annotations

import pytest
from agents import FunctionTool

from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.ingestion.document_environment import DocumentEnvironment, DocumentEnvironmentError
from jurisnexo.ingestion.sdk_structure_agent import (
    StructureAgentContext,
    bound_tool_output,
    build_structure_agent,
    render_printed_page_range,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _environment() -> DocumentEnvironment:
    return DocumentEnvironment(
        ("continuation", "SENTENCIA Pelayo Fernández"),
        printed_page_numbers=(353, 354),
        source_references=(
            "physical_pages=173,174; side=right",
            "physical_pages=175,176; side=left",
        ),
    )


def test_structure_agent_uses_structured_output_and_document_tools() -> None:
    agent = build_structure_agent(model="gemini/gemini-3.8-flash")

    assert agent.name == "JurisNexo Structure Agent"
    assert agent.output_type == DocumentStructureHypothesis
    function_tools = [tool for tool in agent.tools if isinstance(tool, FunctionTool)]
    assert len(function_tools) == len(agent.tools)
    assert {tool.name for tool in function_tools} == {
        "get_page",
        "get_pages",
        "get_printed_page",
        "get_printed_pages",
        "search_text",
    }


def test_printed_range_rendering_preserves_page_identity_and_provenance() -> None:
    page_range = _environment().get_printed_pages(353, 354)

    rendered = render_printed_page_range(page_range)

    assert "view_page=1 | printed_page=353" in rendered
    assert "physical_pages=173,174; side=right" in rendered
    assert "view_page=2 | printed_page=354" in rendered
    assert "physical_pages=175,176; side=left" in rendered


def test_tool_output_budget_rejects_oversized_evidence() -> None:
    context = StructureAgentContext(environment=_environment(), max_tool_output_chars=1_000)

    with pytest.raises(DocumentEnvironmentError, match="narrow the range or search first"):
        bound_tool_output(context, "x" * 1_001)


def test_structure_agent_context_rejects_invalid_budget() -> None:
    with pytest.raises(ValueError, match="at least 1000"):
        StructureAgentContext(environment=_environment(), max_tool_output_chars=999)
