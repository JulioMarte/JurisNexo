from __future__ import annotations

import pytest
from agents import FunctionTool

from jurisnexo.ingestion.decision_reconstruction import (
    DecisionBoundary,
    SourceFaithfulDecision,
    reconstruct_source_faithful_decision,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.sdk_extraction_agent import (
    ExtractionAnnotations,
    build_extraction_agent,
    render_decision_page,
    search_bounded_decision,
    validate_extraction_annotations,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _decision() -> SourceFaithfulDecision:
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
    payload = {
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
    annotations = ExtractionAnnotations.model_validate(payload)
    validate_extraction_annotations(annotations=annotations, decision=decision)

    payload["metadata"][0]["evidence"][0]["exact_text"] = "invented"
    bad = ExtractionAnnotations.model_validate(payload)
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


def test_decision_page_helper_rejects_neighbor_page() -> None:
    with pytest.raises(ValueError, match="outside the bounded decision"):
        render_decision_page(_decision(), 1)


def test_search_is_confined_to_bounded_decision() -> None:
    decision = _decision()

    previous = search_bounded_decision(decision, "PREVIOUS")
    target = search_bounded_decision(decision, "Artículo 12")

    assert previous == "No literal hits."
    assert "view_page=3" in target
    assert "Artículo 12" in target
