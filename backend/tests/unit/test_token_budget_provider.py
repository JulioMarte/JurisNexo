from __future__ import annotations

from dataclasses import dataclass

import pytest

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelUsage,
    StructuredGenerationResult,
)
from jurisnexo.model_providers.token_budget import (
    ModelTokenBudgetExceeded,
    TokenBudgetedModelProvider,
)

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class RecordingProvider:
    input_tokens: int = 100
    returned_total_tokens: int = 150
    requested_max_output_tokens: int | None = None

    @property
    def provider_name(self) -> str:
        return "recording"

    @property
    def model_name(self) -> str:
        return "recording-model"

    def count_input_tokens(self, text: str) -> int:
        del text
        return self.input_tokens

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        del prompt, json_schema, thinking_level
        self.requested_max_output_tokens = max_output_tokens
        return StructuredGenerationResult(
            value={"ok": True},
            provider=self.provider_name,
            model=self.model_name,
            model_version=None,
            response_id="response-1",
            usage=ModelUsage(
                input_tokens=self.input_tokens,
                output_tokens=20,
                thinking_tokens=30,
                total_tokens=self.returned_total_tokens,
            ),
        )


def test_generation_is_clamped_to_remaining_run_budget() -> None:
    inner = RecordingProvider(input_tokens=200, returned_total_tokens=300)
    provider = TokenBudgetedModelProvider(provider=inner, max_total_tokens=1000)
    provider.consumed_total_tokens = 400

    provider.generate_structured(
        prompt="large synthesis",
        json_schema={"type": "object"},
        max_output_tokens=1000,
        thinking_level="medium",
    )

    assert inner.requested_max_output_tokens == 400
    assert provider.consumed_total_tokens == 700


def test_small_explicit_output_limit_is_preserved() -> None:
    inner = RecordingProvider(input_tokens=100, returned_total_tokens=150)
    provider = TokenBudgetedModelProvider(provider=inner, max_total_tokens=1000)

    provider.generate_structured(
        prompt="decision",
        json_schema={"type": "object"},
        max_output_tokens=128,
        thinking_level="low",
    )

    assert inner.requested_max_output_tokens == 128


def test_call_is_rejected_when_prompt_alone_exhausts_budget() -> None:
    inner = RecordingProvider(input_tokens=700)
    provider = TokenBudgetedModelProvider(provider=inner, max_total_tokens=1000)
    provider.consumed_total_tokens = 400

    with pytest.raises(ModelTokenBudgetExceeded, match="cannot fit"):
        provider.generate_structured(
            prompt="too large",
            json_schema={"type": "object"},
            max_output_tokens=500,
            thinking_level="medium",
        )

    assert inner.requested_max_output_tokens is None
