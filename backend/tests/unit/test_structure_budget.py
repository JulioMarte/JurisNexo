from __future__ import annotations

import pytest

from jurisnexo.ingestion.structure_budget import (
    StructureToolBudget,
    StructureToolBudgetExceeded,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant]


def test_tool_budget_allows_varied_evidence_within_limits() -> None:
    budget = StructureToolBudget(max_total_result_chars=10_000, max_identical_calls=2)

    budget.observe_success(
        tool_name="get_page",
        arguments={"page_number": 1},
        result_char_count=2_000,
    )
    budget.observe_success(
        tool_name="get_page",
        arguments={"page_number": 2},
        result_char_count=3_000,
    )

    assert budget.total_result_chars == 5_000


def test_tool_budget_rejects_repeated_identical_calls() -> None:
    budget = StructureToolBudget(max_total_result_chars=10_000, max_identical_calls=2)

    for _ in range(2):
        budget.observe_success(
            tool_name="get_page",
            arguments={"page_number": 7},
            result_char_count=100,
        )

    with pytest.raises(StructureToolBudgetExceeded, match="identical_tool_calls"):
        budget.observe_success(
            tool_name="get_page",
            arguments={"page_number": 7},
            result_char_count=100,
        )


def test_tool_budget_rejects_excessive_total_materialized_evidence() -> None:
    budget = StructureToolBudget(max_total_result_chars=10_000, max_identical_calls=4)

    budget.observe_success(
        tool_name="get_pages",
        arguments={"start_page": 1, "end_page": 10},
        result_char_count=6_000,
    )

    with pytest.raises(StructureToolBudgetExceeded, match="total_tool_result_chars"):
        budget.observe_success(
            tool_name="search_text",
            arguments={"query": "SENTENCIA"},
            result_char_count=5_000,
        )