from __future__ import annotations

import pytest

from jurisnexo.bootstrap.settings import NormalizationModelSettings, OpenRouterSettings
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider


def test_openrouter_secret_is_optional_for_offline_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = OpenRouterSettings()
    assert settings.api_key is None
    assert settings.base_url == "https://openrouter.ai/api/v1"


def test_normalization_model_policy_defaults_to_moving_cost_first_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JURISNEXO_OPENROUTER_JEV_MODEL", raising=False)
    monkeypatch.delenv("JURISNEXO_OPENROUTER_DEEPSEEK_MODEL", raising=False)
    settings = NormalizationModelSettings()
    assert settings.jev_model == "~typesafe/jev-latest"
    assert settings.deepseek_model == "~deepseek/deepseek-v4-flash-latest"


def test_live_provider_rejects_missing_secret_before_network() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenRouterStructuredModelProvider(api_key="", model="fixture")
