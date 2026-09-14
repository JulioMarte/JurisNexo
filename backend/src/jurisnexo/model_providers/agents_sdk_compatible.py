from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agents import OpenAIChatCompletionsModel
from agents.models.interface import Model, ModelProvider
from agents.models.reasoning_content_replay import ReasoningContentReplayContext
from openai import AsyncOpenAI

CompatibleProviderName = Literal["gemini", "deepseek"]

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# Transport must always fail before any long-running agent-level safety fuse.  The
# Agents SDK layer owns semantic retries; the OpenAI-compatible HTTP client only
# provides a bounded attempt so one stalled socket cannot consume an entire run.
_COMPATIBLE_REQUEST_TIMEOUT_SECONDS = 90.0


def _replay_provider_reasoning(_context: ReasoningContentReplayContext) -> bool:
    """Replay provider-exposed reasoning needed by DeepSeek tool-use turns."""

    return True


@dataclass(slots=True)
class CompatibleEndpointModelProvider(ModelProvider):
    """Resolve Agents SDK models through provider OpenAI-compatible endpoints."""

    provider_name: CompatibleProviderName
    api_key: str
    _client: AsyncOpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError(f"{self.provider_name} API key is required")
        base_url = (
            _GEMINI_BASE_URL if self.provider_name == "gemini" else _DEEPSEEK_BASE_URL
        )
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=_COMPATIBLE_REQUEST_TIMEOUT_SECONDS,
            # Keep transport retries disabled here. Runner-managed retries have
            # replay-safety information that the raw HTTP client does not.
            max_retries=0,
        )

    def get_model(self, model_name: str | None) -> Model:
        if model_name is None or not model_name.strip():
            raise ValueError("an explicit model name is required")
        replay_reasoning = (
            _replay_provider_reasoning if self.provider_name == "deepseek" else None
        )
        return OpenAIChatCompletionsModel(
            model=model_name,
            openai_client=self._client,
            should_replay_reasoning_content=replay_reasoning,
        )


def build_compatible_model_provider(
    *, provider: CompatibleProviderName, api_key: str
) -> CompatibleEndpointModelProvider:
    return CompatibleEndpointModelProvider(provider_name=provider, api_key=api_key)
