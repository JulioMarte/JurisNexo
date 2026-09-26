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


def test_text_provider_retries_invalid_structure_on_different_provider() -> None:
    import json

    from jurisnexo.model_providers.contracts import JsonObject
    from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider

    class RetryProvider(OpenRouterStructuredModelProvider):
        payloads: list[JsonObject]

        def __post_init__(self) -> None:
            super().__post_init__()
            self.payloads = []

        def _post_payload(self, payload: JsonObject) -> bytes:
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                return json.dumps(
                    {
                        "id": "first",
                        "model": self.model,
                        "provider": "Wafer",
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                            "cost": 0.001,
                        },
                        "choices": [
                            {
                                "message": {
                                    "content": "I will reason in prose instead."
                                }
                            }
                        ],
                    }
                ).encode()
            return json.dumps(
                {
                    "id": "second",
                    "model": self.model,
                    "provider": "Backup",
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 3,
                        "total_tokens": 14,
                        "cost": 0.002,
                    },
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "arguments": '{"ok": true}'
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                }
            ).encode()

    schema: JsonObject = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    provider = RetryProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="tool",
        allow_provider_fallbacks=True,
        max_structured_attempts=2,
    )
    result = provider.generate_structured(
        prompt="fixture",
        json_schema=schema,
        max_output_tokens=50,
        thinking_level="none",
    )

    assert result.value == {"ok": True}
    assert result.usage.input_tokens == 21
    assert result.usage.output_tokens == 8
    assert result.usage.total_tokens == 29
    assert result.cost_usd == 0.003
    assert result.provider_metadata is not None
    assert result.provider_metadata["structured_attempt_count"] == 2
    assert result.provider_metadata["ignored_providers_on_retry"] == ["Wafer"]
    assert provider.payloads[1]["provider"] == {
        "require_parameters": True,
        "allow_fallbacks": True,
        "sort": "price",
        "ignore": ["Wafer"],
    }


def test_text_provider_does_not_retry_http_or_transport_failures() -> None:
    from jurisnexo.model_providers.contracts import JsonObject, ModelProviderError
    from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider

    class TransportFailureProvider(OpenRouterStructuredModelProvider):
        calls: int = 0

        def _post_payload(self, payload: JsonObject) -> bytes:
            del payload
            self.calls += 1
            raise ModelProviderError("transport failed")

    provider = TransportFailureProvider(
        api_key="test-key",
        model="fixture",
        structured_mode="tool",
        max_structured_attempts=2,
    )
    try:
        provider.generate_structured(
            prompt="fixture",
            json_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            max_output_tokens=50,
            thinking_level="none",
        )
    except ModelProviderError:
        pass
    else:
        raise AssertionError("transport failure must propagate")
    assert provider.calls == 1
