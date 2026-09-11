from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from jurisnexo.model_providers.contracts import (
    InputTokenCountingProvider,
    JsonObject,
    ModelProvider,
    ModelProviderError,
    ModelProviderIncompleteError,
    StructuredGenerationResult,
)


class ModelTokenBudgetExceeded(ModelProviderError):
    """Raised before a model call when the run token budget cannot fit it."""


@dataclass(slots=True)
class TokenBudgetedModelProvider:
    """Clamp each generation to the run's remaining provider-token budget.

    The caller may request a generous per-call output ceiling. This wrapper
    subtracts already consumed provider-reported tokens and the next prompt's
    input tokens before forwarding the request, so thinking + visible output
    cannot knowingly exceed the remaining run budget.
    """

    provider: ModelProvider
    max_total_tokens: int
    consumed_total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.max_total_tokens < 1:
            raise ValueError("max_total_tokens must be positive")

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    @property
    def model_name(self) -> str:
        return self.provider.model_name

    def count_input_tokens(self, text: str) -> int:
        if isinstance(self.provider, InputTokenCountingProvider):
            return self.provider.count_input_tokens(text)
        return max(1, ceil(len(text) / 4))

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        input_tokens = self.count_input_tokens(prompt)
        remaining_for_generation = (
            self.max_total_tokens - self.consumed_total_tokens - input_tokens
        )
        if remaining_for_generation < 1:
            raise ModelTokenBudgetExceeded(
                "model token budget cannot fit the next prompt: "
                f"consumed={self.consumed_total_tokens}, "
                f"input={input_tokens}, max_total={self.max_total_tokens}"
            )
        effective_max_output = min(max_output_tokens, remaining_for_generation)
        try:
            result = self.provider.generate_structured(
                prompt=prompt,
                json_schema=json_schema,
                max_output_tokens=effective_max_output,
                thinking_level=thinking_level,
            )
        except ModelProviderIncompleteError as exc:
            self._record_usage(exc.usage.total_tokens)
            raise
        self._record_usage(result.usage.total_tokens)
        return result

    def _record_usage(self, total_tokens: int | None) -> None:
        if total_tokens is None:
            return
        self.consumed_total_tokens += total_tokens
        if self.consumed_total_tokens > self.max_total_tokens:
            raise ModelTokenBudgetExceeded(
                "provider-reported model token budget exceeded: "
                f"{self.consumed_total_tokens} > {self.max_total_tokens}"
            )
