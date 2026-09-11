from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.model_providers.contracts import JsonObject, ModelProviderError
from jurisnexo.model_providers.google_gemini import (
    GeminiTransportError,
    GoogleGeminiProvider,
)

pytestmark = pytest.mark.unit


def _empty_delays() -> list[float]:
    return []


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


@dataclass(slots=True)
class SequenceTransport:
    outcomes: tuple[JsonObject | GeminiTransportError, ...]
    calls: int = 0

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        del url, headers, payload, timeout_seconds
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, GeminiTransportError):
            raise outcome
        return outcome


@dataclass(slots=True)
class RecordingSleep:
    delays: list[float] = field(default_factory=_empty_delays)

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _success_response() -> JsonObject:
    return {
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


def test_structured_generation_sends_schema_and_parses_usage() -> None:
    transport = RecordingTransport(response=_success_response())
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


def test_retryable_transport_failure_recovers_with_bounded_backoff() -> None:
    transport = SequenceTransport(
        outcomes=(
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
            _success_response(),
        )
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=4,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=8.0,
        sleep=sleep,
    )

    result = provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )

    assert result.value == {"artifact_class": "compilation"}
    assert transport.calls == 3
    assert sleep.delays == [1.0, 2.0]


def test_non_retryable_transport_failure_fails_immediately() -> None:
    transport = SequenceTransport(
        outcomes=(GeminiTransportError("Gemini HTTP error 400", retryable=False),)
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=4,
        sleep=sleep,
    )

    with pytest.raises(GeminiTransportError, match="400"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=512,
            thinking_level="medium",
        )

    assert transport.calls == 1
    assert sleep.delays == []


def test_retryable_failure_stops_at_attempt_limit() -> None:
    transport = SequenceTransport(
        outcomes=(
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
        )
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    with pytest.raises(GeminiTransportError, match="503"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=512,
            thinking_level="medium",
        )

    assert transport.calls == 2
    assert sleep.delays == [1.0]


def test_missing_api_key_fails_closed() -> None:
    provider = GoogleGeminiProvider(api_key="")

    with pytest.raises(ModelProviderError, match="GEMINI_API_KEY"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=128,
            thinking_level="low",
        )
