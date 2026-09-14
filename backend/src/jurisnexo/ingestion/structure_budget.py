from __future__ import annotations

import json
from dataclasses import dataclass, field


class StructureToolBudgetExceeded(RuntimeError):
    """Raised when investigation exceeds a non-turn safety fuse."""

    def __init__(self, *, dimension: str, limit: int, observed: int, detail: str) -> None:
        self.dimension = dimension
        self.limit = limit
        self.observed = observed
        self.detail = detail
        super().__init__(
            f"structure investigation exceeded {dimension} budget: "
            f"observed={observed}, limit={limit}; {detail}"
        )


def _empty_call_counts() -> dict[str, int]:
    return {}


@dataclass(slots=True)
class StructureToolBudget:
    """Mutable per-agent safety budget; it constrains waste, not reasoning strategy."""

    max_total_result_chars: int = 750_000
    max_identical_calls: int = 4
    total_result_chars: int = 0
    identical_call_counts: dict[str, int] = field(default_factory=_empty_call_counts)

    def __post_init__(self) -> None:
        if self.max_total_result_chars < 10_000:
            raise ValueError("max_total_result_chars must be at least 10000")
        if self.max_identical_calls < 1:
            raise ValueError("max_identical_calls must be positive")

    def observe_success(
        self,
        *,
        tool_name: str,
        arguments: dict[str, int | str],
        result_char_count: int,
    ) -> None:
        if result_char_count < 0:
            raise ValueError("result_char_count must not be negative")

        call_key = json.dumps(
            {"tool_name": tool_name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        repeated = self.identical_call_counts.get(call_key, 0) + 1
        self.identical_call_counts[call_key] = repeated
        if repeated > self.max_identical_calls:
            raise StructureToolBudgetExceeded(
                dimension="identical_tool_calls",
                limit=self.max_identical_calls,
                observed=repeated,
                detail=f"tool={tool_name}; arguments={arguments}",
            )

        self.total_result_chars += result_char_count
        if self.total_result_chars > self.max_total_result_chars:
            raise StructureToolBudgetExceeded(
                dimension="total_tool_result_chars",
                limit=self.max_total_result_chars,
                observed=self.total_result_chars,
                detail="narrow future reads or searches rather than materializing more evidence",
            )