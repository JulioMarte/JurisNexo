from __future__ import annotations

import pytest
from agents import FunctionTool

from jurisnexo.ingestion.decision_reconstruction import (
    DecisionBoundary,
    reconstruct_source_faithful_decision,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.sdk_extraction_agent import (
    ExtractionAnnotations,
    ExtractionAgentContext,
    build_extraction_agent,
    get_decision_page,
    search_decision_text,
    validate_extraction_annotations,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _decision():
    environment = DocumentEnvironment(
        (
            "PREVIOUS DECISION",
            "CORTE SUPREMA\nSENTENCIA 12-2026\nJuan Pérez contra ACME",
            "La Corte decide ACOGER el recurso. Artículo 12 de la Ley 1-24.",
            "NEXT DECISION",
        ),
        printed_page_numbers=(10, 11, 12, 13),
    )
    return reconstruct_source_faithful_decision(
        environment=environment,
        boundary=DecisionBoundary(start_view_page=2, end_view_page=3),
    )


def test_extraction_agent_has_only_bounded_decision_tools() -> None:
    agent = build_extraction_agent(model="gpt-5.6-luna")

    assert agent.name == "JurisNexo Extraction Agent"
    assert agent.output_type == ExtractionAnnotations
    tools = [tool for tool in agent.tools if isinstance(tool, FunctionTool)]
    assert {tool.name for tool in tools} == {"get_decision_page", "search_decision_text"}


def test_evidence_spans_must_match_exact_source_text() -> None:
    decision = _decision()
    page_text = decision.pages[0].text
    exact = "SENTENCIA 12-2026"
    start = page_text.index(exact)
    annotations = ExtractionAnnotations.model_validate(
        {
            "metadata": [
                {
                    "field": "decision_number",
                    "value": "12-2026",
                    "confidence": 0.99,
                    "evidence": [
                        {
                            "view_page": 2,
                            "char_start": start,
                            "char_end": start + len(exact),
                            "exact_text": exact,
                        }
                    ],
                }
            ]
        }
    )

    validate_extraction_annotations(annotations=annotations, decision=decision)

    bad = annotations.model_copy(deep=True)
    bad.metadata[0].evidence[0].exact_text = "invented"
    with pytest.raises(ValueError, match="does not match source"):
        validate_extraction_annotations(annotations=bad, decision=decision)


def test_evidence_outside_bounded_decision_is_rejected() -> None:
    decision = _decision()
    annotations = ExtractionAnnotations.model_validate(
        {
            "metadata": [
                {
                    "field": "party",
                    "value": "Previous party",
                    "confidence": 0.9,
                    "evidence": [
                        {
                            "view_page": 1,
                            "char_start": 0,
                            "char_end": 8,
                            "exact_text": "PREVIOUS",
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="outside the decision"):
        validate_extraction_annotations(annotations=annotations, decision=decision)


@pytest.mark.asyncio
async def test_get_decision_page_rejects_neighbor_page() -> None:
    context = ExtractionAgentContext(decision=_decision())

    class Wrapper:
        def __init__(self, value: ExtractionAgentContext) -> None:
            self.context = value

    with pytest.raises(ValueError, match="outside the bounded decision"):
        await get_decision_page.on_invoke_tool(Wrapper(context), '{"view_page": 1}')


@pytest.mark.asyncio
async def test_search_is_confined_to_bounded_decision() -> None:
    context = ExtractionAgentContext(decision=_decision())

    class Wrapper:
        def __init__(self, value: ExtractionAgentContext) -> None:
            self.context = value

    previous = await search_decision_text.on_invoke_tool(Wrapper(context), '{"query": "PREVIOUS"}')
    target = await search_decision_text.on_invoke_tool(Wrapper(context), '{"query": "Artículo 12"}')

    assert previous == "No literal hits."
    assert "view_page=3" in target
    assert "Artículo 12" in target
