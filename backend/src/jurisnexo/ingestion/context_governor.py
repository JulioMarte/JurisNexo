from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from jurisnexo.model_providers.contracts import InputTokenCountingProvider, ModelProvider


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """Configurable context policy; values are runtime policy, not tool page limits."""

    parent_soft_limit_tokens: int = 120_000
    delegated_soft_limit_tokens: int = 120_000

    def __post_init__(self) -> None:
        if self.parent_soft_limit_tokens < 1:
            raise ValueError("parent_soft_limit_tokens must be positive")
        if self.delegated_soft_limit_tokens < 1:
            raise ValueError("delegated_soft_limit_tokens must be positive")


@dataclass(frozen=True, slots=True)
class TokenCount:
    tokens: int
    exact: bool
    method: str


@dataclass(frozen=True, slots=True)
class ContextPreflight:
    active_context_tokens: int
    requested_evidence_tokens: int
    projected_context_tokens: int
    soft_limit_tokens: int
    should_inline: bool
    exact: bool
    counting_method: str


class ContextGovernor:
    def __init__(self, provider: ModelProvider, policy: ContextPolicy | None = None) -> None:
        self._provider = provider
        self.policy = policy or ContextPolicy()

    def count(self, text: str) -> TokenCount:
        if isinstance(self._provider, InputTokenCountingProvider):
            return TokenCount(
                tokens=self._provider.count_input_tokens(text),
                exact=True,
                method="provider_tokenizer",
            )
        # Conservative fallback for providers without a tokenizer endpoint.
        # It is intentionally labeled approximate in every preflight response.
        return TokenCount(
            tokens=max(1, ceil(len(text) / 4)),
            exact=False,
            method="approx_chars_div_4",
        )

    def preflight_parent(self, *, active_prompt: str, evidence: str) -> ContextPreflight:
        active = self.count(active_prompt)
        requested = self.count(evidence)
        projected = active.tokens + requested.tokens
        return ContextPreflight(
            active_context_tokens=active.tokens,
            requested_evidence_tokens=requested.tokens,
            projected_context_tokens=projected,
            soft_limit_tokens=self.policy.parent_soft_limit_tokens,
            should_inline=projected <= self.policy.parent_soft_limit_tokens,
            exact=active.exact and requested.exact,
            counting_method=(
                active.method if active.method == requested.method else f"{active.method}+{requested.method}"
            ),
        )

    def fits_delegated_context(self, text: str) -> bool:
        return self.count(text).tokens <= self.policy.delegated_soft_limit_tokens
