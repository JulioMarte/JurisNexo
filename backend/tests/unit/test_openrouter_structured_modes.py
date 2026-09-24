from __future__ import annotations


def test_text_provider_tool_mode_forces_function_call() -> None:
    from jurisnexo.model_providers.contracts import JsonObject
    from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider

    class TestProvider(OpenRouterStructuredModelProvider):
        def apply_structured_output(
            self,
            *,
            payload: JsonObject,
            json_schema: JsonObject,
        ) -> None:
            self._apply_structured_output(
                payload=payload,
                json_schema=json_schema,
            )

        def provider_routing(self) -> JsonObject:
            return self._provider_routing()

    schema: JsonObject = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    provider = TestProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="tool",
        provider_order=("DeepSeek",),
    )
    payload: JsonObject = {}
    provider.apply_structured_output(payload=payload, json_schema=schema)
    assert "response_format" not in payload
    assert payload["tool_choice"] == "required"
    assert provider.provider_routing() == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "order": ["DeepSeek"],
    }


def test_text_provider_json_object_mode_is_explicit() -> None:
    from jurisnexo.model_providers.contracts import JsonObject
    from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider

    class TestProvider(OpenRouterStructuredModelProvider):
        def apply_structured_output(
            self,
            *,
            payload: JsonObject,
            json_schema: JsonObject,
        ) -> None:
            self._apply_structured_output(
                payload=payload,
                json_schema=json_schema,
            )

    schema: JsonObject = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    provider = TestProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="json_object",
    )
    payload: JsonObject = {}
    provider.apply_structured_output(payload=payload, json_schema=schema)
    assert payload["response_format"] == {"type": "json_object"}


def test_visual_provider_defaults_to_tool_mode() -> None:
    from jurisnexo.model_providers.contracts import JsonObject
    from jurisnexo.model_providers.openrouter_visual import (
        OpenRouterVisualModelProvider,
    )

    class TestProvider(OpenRouterVisualModelProvider):
        def apply_structured_output(
            self,
            *,
            payload: JsonObject,
            json_schema: JsonObject,
        ) -> None:
            self._apply_structured_output(
                payload=payload,
                json_schema=json_schema,
            )

    schema: JsonObject = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    provider = TestProvider(
        api_key="test-key",
        model="fixture",
    )
    payload: JsonObject = {}
    provider.apply_structured_output(payload=payload, json_schema=schema)
    assert provider.structured_mode == "tool"
    assert "tools" in payload
    assert "response_format" not in payload


def test_visual_provider_unpinned_routing_stays_parameter_safe() -> None:
    from jurisnexo.model_providers.contracts import JsonObject
    from jurisnexo.model_providers.openrouter_visual import (
        OpenRouterVisualModelProvider,
    )

    class TestProvider(OpenRouterVisualModelProvider):
        def provider_routing(self) -> JsonObject:
            return self._provider_routing()

    provider = TestProvider(
        api_key="test-key",
        model="fixture",
    )
    assert provider.provider_routing() == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "sort": "price",
    }
