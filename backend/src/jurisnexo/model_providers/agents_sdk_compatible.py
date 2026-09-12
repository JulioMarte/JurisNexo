from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agents import OpenAIChatCompletionsModel
from agents.models.interface import Model, ModelProvider
from openai import AsyncOpenAI

CompatibleProviderName = Literal["gemini", "deepseek"]

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


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
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)

    def get_model(self, model_name: str | None) -> Model:
        if model_name is None or not model_name.strip():
            raise ValueError("an explicit model name is required")
        return OpenAIChatCompletionsModel(
            model=model_name,
            openai_client=self._client,
        )


def build_compatible_model_provider(
    *, provider: CompatibleProviderName, api_key: str
) -> CompatibleEndpointModelProvider:
    return CompatibleEndpointModelProvider(provider_name=provider, api_key=api_key)
