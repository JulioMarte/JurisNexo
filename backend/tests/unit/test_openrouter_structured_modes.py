from __future__ import annotations

from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def test_text_provider_tool_mode_forces_function_call() -> None:
    provider = OpenRouterStructuredModelProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="tool",
        provider_order=("DeepSeek",),
    )
    payload: dict[str, object] = {}
    provider._apply_structured_output(payload=payload, json_schema=SCHEMA)
    assert "response_format" not in payload
    assert payload["tool_choice"] == "required"
    assert provider._provider_routing() == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "order": ["DeepSeek"],
    }


def test_text_provider_json_object_mode_is_explicit() -> None:
    provider = OpenRouterStructuredModelProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="json_object",
    )
    payload: dict[str, object] = {}
    provider._apply_structured_output(payload=payload, json_schema=SCHEMA)
    assert payload["response_format"] == {"type": "json_object"}


def test_visual_provider_defaults_to_tool_mode() -> None:
    provider = OpenRouterVisualModelProvider(
        api_key="test-key",
        model="fixture",
    )
    payload: dict[str, object] = {}
    provider._apply_structured_output(payload=payload, json_schema=SCHEMA)
    assert provider.structured_mode == "tool"
    assert "tools" in payload
    assert "response_format" not in payload


def test_visual_provider_unpinned_routing_stays_parameter_safe() -> None:
    provider = OpenRouterVisualModelProvider(
        api_key="test-key",
        model="fixture",
    )
    assert provider._provider_routing() == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "sort": "price",
    }
