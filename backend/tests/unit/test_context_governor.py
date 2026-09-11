from __future__ import annotations

from dataclasses import dataclass

import pytest

from jurisnexo.ingestion.context_governor import ContextGovernor, ContextPolicy
from jurisnexo.model_providers.contracts import JsonObject, ModelUsage, StructuredGenerationResult

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class ExactCountingProvider:
    @property
    def provider_name(self) -> str:
        return "exact"

    @property
    def model_name(self) -> str:
        return "exact-model"

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
        del prompt, json_schema, max_output_tokens, thinking_level
        raise AssertionError("not used")


@dataclass(slots=True)
class NoCountingProvider:
    @property
    def provider_name(self) -> str:
        return "fallback"

    @property
    def model_name(self) -> str:
        return "fallback-model"

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        del prompt, json_schema, max_output_tokens, thinking_level
        return StructuredGenerationResult(
            value={}, provider="fallback", model="fallback-model", model_version=None,
            response_id=None, usage=ModelUsage()
        )


def test_preflight_uses_provider_tokenizer_when_available() -> None:
    governor = ContextGovernor(
        ExactCountingProvider(), ContextPolicy(parent_soft_limit_tokens=10)
    )
    result = governor.preflight_parent(active_prompt="1234", evidence="56789")
    assert result.active_context_tokens == 4
    assert result.requested_evidence_tokens == 5
    assert result.projected_context_tokens == 9
    assert result.should_inline is True
    assert result.exact is True
    assert result.counting_method == "provider_tokenizer"


def test_preflight_rejects_inline_when_projected_context_exceeds_soft_limit() -> None:
    governor = ContextGovernor(
        ExactCountingProvider(), ContextPolicy(parent_soft_limit_tokens=8)
    )
    result = governor.preflight_parent(active_prompt="1234", evidence="56789")
    assert result.projected_context_tokens == 9
    assert result.should_inline is False


def test_fallback_counter_is_explicitly_approximate() -> None:
    governor = ContextGovernor(NoCountingProvider())
    count = governor.count("x" * 40)
    assert count.tokens == 10
    assert count.exact is False
    assert count.method == "approx_chars_div_4"
