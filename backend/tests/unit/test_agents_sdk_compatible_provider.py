from __future__ import annotations

import pytest
from agents import OpenAIChatCompletionsModel

from jurisnexo.model_providers.agents_sdk_compatible import (
    CompatibleEndpointModelProvider,
    build_compatible_model_provider,
)

pytestmark = pytest.mark.unit


def test_gemini_provider_requires_explicit_model_name() -> None:
    provider = build_compatible_model_provider(provider="gemini", api_key="test-key")

    with pytest.raises(ValueError, match="explicit model"):
        provider.get_model(None)


def test_deepseek_provider_requires_explicit_model_name() -> None:
    provider = build_compatible_model_provider(provider="deepseek", api_key="test-key")

    with pytest.raises(ValueError, match="explicit model"):
        provider.get_model("")


def test_provider_resolves_agents_sdk_chat_model_without_network_call() -> None:
    provider = CompatibleEndpointModelProvider(provider_name="gemini", api_key="test-key")

    model = provider.get_model("gemini-3.8-flash")

    assert isinstance(model, OpenAIChatCompletionsModel)


def test_provider_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        CompatibleEndpointModelProvider(provider_name="deepseek", api_key="")
