from __future__ import annotations

import pytest

from jurisnexo.bootstrap.settings import NormalizationModelSettings, OpenRouterSettings
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider


def test_openrouter_secret_is_optional_for_offline_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = OpenRouterSettings()
    assert settings.api_key is None
    assert settings.base_url == "https://openrouter.ai/api/v1"


def test_normalization_model_policy_pins_official_visual_judge_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "JEV_MODEL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_REASONING_EFFORT",
        "DEEPSEEK_STRUCTURED_MODE",
        "DEEPSEEK_PROVIDER_ORDER",
        "DEEPSEEK_ALLOW_PROVIDER_FALLBACKS",
        "LUNA_MODEL",
        "LUNA_REASONING_EFFORT",
        "LUNA_STRUCTURED_MODE",
        "LUNA_PROVIDER_ORDER",
        "LUNA_ALLOW_PROVIDER_FALLBACKS",
    ):
        monkeypatch.delenv(f"JURISNEXO_OPENROUTER_{name}", raising=False)
    settings = NormalizationModelSettings()
    assert settings.jev_model == "~typesafe/jev-latest"
    assert settings.deepseek_model == "deepseek/deepseek-v4.1-flash"
    assert settings.deepseek_reasoning_effort == "high"
    assert settings.deepseek_structured_mode == "json_schema"
    assert settings.deepseek_provider_order == "DeepSeek"
    assert settings.deepseek_allow_provider_fallbacks is False
    assert settings.luna_model == "openai/gpt-6-luna"
    assert settings.luna_reasoning_effort == "high"
    assert settings.luna_structured_mode == "json_schema"
    assert settings.luna_provider_order == "OpenAI"
    assert settings.luna_allow_provider_fallbacks is False


def test_live_provider_rejects_missing_secret_before_network() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenRouterStructuredModelProvider(api_key="", model="fixture")
