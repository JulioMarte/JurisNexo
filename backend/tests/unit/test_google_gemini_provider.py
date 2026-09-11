from __future__ import annotations

from dataclasses import dataclass

import pytest

from jurisnexo.model_providers.contracts import JsonObject, ModelProviderError
from jurisnexo.model_providers.google_gemini import GoogleGeminiProvider

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class RecordingTransport:
    response: JsonObject
    last_url: str | None = None
    last_headers: dict[str, str] | None = None
    last_payload: JsonObject | None = None

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        del timeout_seconds
        self.last_url = url
        self.last_headers = headers
        self.last_payload = payload
        return self.response


def test_structured_generation_sends_schema_and_parses_usage() -> None:
    transport = RecordingTransport(
        response={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"artifact_class":"compilation"}',
                            }
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 4,
                "thoughtsTokenCount": 3,
                "totalTokenCount": 17,
            },
            "modelVersion": "gemini-3.8-flash-001",
            "responseId": "response-1",
        }
    )
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        model="gemini-3.8-flash",
        transport=transport,
    )

    result = provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )

    assert result.value == {"artifact_class": "compilation"}
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 4
    assert result.usage.thinking_tokens == 3
    assert result.model_version == "gemini-3.8-flash-001"
    assert transport.last_url is not None
    assert transport.last_url.endswith("gemini-3.8-flash:generateContent")
    assert transport.last_headers == {
        "Content-Type": "application/json",
        "x-goog-api-key": "test-secret",
    }
    assert transport.last_payload is not None
    config = transport.last_payload["generationConfig"]
    assert isinstance(config, dict)
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == {"type": "object"}
    assert config["thinkingConfig"] == {"thinkingLevel": "medium"}


def test_missing_api_key_fails_closed() -> None:
    provider = GoogleGeminiProvider(api_key="")

    with pytest.raises(ModelProviderError, match="GEMINI_API_KEY"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=128,
            thinking_level="low",
        )
