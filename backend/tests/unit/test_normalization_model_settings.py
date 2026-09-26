from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurisnexo.bootstrap.settings import NormalizationModelSettings


@pytest.mark.parametrize(
    "mode",
    ["tool", "json_schema", "json_object", "prompt_json"],
)
def test_deepseek_structured_modes_are_accepted(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("JURISNEXO_OPENROUTER_DEEPSEEK_STRUCTURED_MODE", mode)

    settings = NormalizationModelSettings()

    assert settings.deepseek_structured_mode == mode


def test_prompt_json_is_available_to_luna_for_provider_compatibility() -> None:
    settings = NormalizationModelSettings(luna_structured_mode="prompt_json")

    assert settings.luna_structured_mode == "prompt_json"


def test_unknown_structured_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizationModelSettings(deepseek_structured_mode="not-a-mode")
