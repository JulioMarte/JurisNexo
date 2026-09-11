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


def _empty_urls() -> list[str]:
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
    urls: list[str] = field(default_factory=_empty_urls)

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        del headers, payload, timeout_seconds
        self.urls.append(url)
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


def _success_response(*, model_version: str = "gemini-3.8-flash-001") -> JsonObject:
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
        "modelVersion": model_version,
        "responseId": "response-1",
    }


def _generate(provider: GoogleGeminiProvider) -> None:
    provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )


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
    assert result.model == "gemini-3.8-flash"
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
            _success_response(),
        )
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=4.0,
        sleep=sleep,
    )

    result = provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )

    assert result.model == "gemini-3.8-flash"
    assert transport.calls == 2
    assert sleep.delays == [1.0]
    assert all("gemini-3.8-flash" in url for url in transport.urls)


def test_transient_primary_exhaustion_fails_over_and_pins_fallback() -> None:
    transport = SequenceTransport(
        outcomes=(
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
            GeminiTransportError("Gemini HTTP error 503", retryable=True),
            _success_response(model_version="gemini-3.7-flash-001"),
            _success_response(model_version="gemini-3.7-flash-001"),
        )
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    first = provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )
    second = provider.generate_structured(
        prompt="inspect again",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )

    assert first.model == "gemini-3.7-flash"
    assert second.model == "gemini-3.7-flash"
    assert provider.model_name == "gemini-3.7-flash"
    assert transport.calls == 4
    assert "gemini-3.8-flash" in transport.urls[0]
    assert "gemini-3.8-flash" in transport.urls[1]
    assert "gemini-3.7-flash" in transport.urls[2]
    assert "gemini-3.7-flash" in transport.urls[3]
    assert sleep.delays == [1.0]


def test_non_retryable_transport_failure_does_not_fail_over() -> None:
    transport = SequenceTransport(
        outcomes=(GeminiTransportError("Gemini HTTP error 400", retryable=False),)
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    with pytest.raises(GeminiTransportError, match="400"):
        _generate(provider)

    assert transport.calls == 1
    assert "gemini-3.8-flash" in transport.urls[0]
    assert sleep.delays == []


def test_all_configured_models_exhaust_transient_failures() -> None:
    transient = GeminiTransportError("Gemini HTTP error 503", retryable=True)
    transport = SequenceTransport(outcomes=(transient, transient, transient, transient))
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    with pytest.raises(GeminiTransportError, match="503"):
        _generate(provider)

    assert transport.calls == 4
    assert "gemini-3.8-flash" in transport.urls[0]
    assert "gemini-3.8-flash" in transport.urls[1]
    assert "gemini-3.7-flash" in transport.urls[2]
    assert "gemini-3.7-flash" in transport.urls[3]
    assert sleep.delays == [1.0, 1.0]


def test_missing_api_key_fails_closed() -> None:
    provider = GoogleGeminiProvider(api_key="")

    with pytest.raises(ModelProviderError, match="GEMINI_API_KEY"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=128,
            thinking_level="low",
        )
