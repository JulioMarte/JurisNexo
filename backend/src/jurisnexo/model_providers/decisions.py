from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jurisnexo.model_providers.contracts import JsonObject

DecisionQuestion = JsonObject
DecisionAnswer = JsonObject


@dataclass(frozen=True, slots=True)
class DecisionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class DecisionResult:
    answers: dict[str, DecisionAnswer]
    provider: str
    model: str
    model_version: str | None
    response_id: str | None
    usage: DecisionUsage
    cost_usd: float | None = None


class DecisionProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def decide(
        self,
        *,
        state_description: str,
        records: tuple[dict[str, str], ...],
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResult: ...
