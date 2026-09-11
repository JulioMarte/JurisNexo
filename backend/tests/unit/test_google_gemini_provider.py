from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelProviderError,
    ModelProviderIncompleteError,
)
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
    last_timeout_seconds: float | None = None

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        self.last_url = url
        self.last_headers = headers
        self.last_payload = payload
        self.last_timeout_seconds = timeout_seconds
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
        "id": "int_test_1",
        "model": "gemini-3.8-flash",
        "status": "completed",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": '{"artifact_class":"compilation"}',
                    }
                ],
            }
        ],
        "usage": {
            "total_input_tokens": 10,
            "total_output_tokens": 4,
            "total_thought_tokens": 3,
            "total_tokens": 17,
        },
    }


def _generate(provider: GoogleGeminiProvider) -> None:
    provider.generate_structured(
        prompt="inspect",
        json_schema={"type": "object"},
        max_output_tokens=512,
        thinking_level="medium",
    )


def test_structured_generation_uses_interactions_flex_and_parses_usage() -> None:
    transport = RecordingTransport(response=_success_response())
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        model="gemini-3.8-flash",
        service_tier="flex",
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
    assert result.response_id == "int_test_1"
    assert result.model_version is None
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 4
    assert result.usage.thinking_tokens == 3
    assert result.usage.total_tokens == 17
    assert transport.last_url == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert transport.last_headers == {
        "Content-Type": "application/json",
        "x-goog-api-key": "test-secret",
    }
    assert transport.last_timeout_seconds == 900.0
    assert transport.last_payload is not None
    assert transport.last_payload["model"] == "gemini-3.8-flash"
    assert transport.last_payload["input"] == "inspect"
    assert transport.last_payload["service_tier"] == "flex"
    assert transport.last_payload["store"] is False
    assert transport.last_payload["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": {"type": "object"},
    }
    assert transport.last_payload["generation_config"] == {
        "max_output_tokens": 512,
        "thinking_level": "medium",
    }


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
        retry_base_delay_seconds=2.0,
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
    assert sleep.delays == [2.0]


def test_default_retry_policy_survives_repeated_high_demand_500s() -> None:
    transient = GeminiTransportError("Gemini HTTP error 500: high demand", retryable=True)
    transport = SequenceTransport(
        outcomes=(transient, transient, transient, _success_response())
    )
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        sleep=sleep,
    )

    _generate(provider)

    assert transport.calls == 4
    assert sleep.delays == [2.0, 4.0, 8.0]


def test_count_tokens_uses_same_retry_policy() -> None:
    transient = GeminiTransportError("Gemini HTTP error 500: high demand", retryable=True)
    transport = SequenceTransport(outcomes=(transient, {"totalTokens": 123}))
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    assert provider.count_input_tokens("evidence") == 123
    assert transport.calls == 2
    assert sleep.delays == [2.0]


def test_non_retryable_transport_failure_fails_immediately() -> None:
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
    assert sleep.delays == []


def test_retryable_failure_stops_at_attempt_limit() -> None:
    transient = GeminiTransportError("Gemini HTTP error 503", retryable=True)
    transport = SequenceTransport(outcomes=(transient, transient))
    sleep = RecordingSleep()
    provider = GoogleGeminiProvider(
        api_key="test-secret",
        transport=transport,
        max_attempts=2,
        sleep=sleep,
    )

    with pytest.raises(GeminiTransportError, match="503"):
        _generate(provider)

    assert transport.calls == 2
    assert sleep.delays == [2.0]


def test_incomplete_interaction_fails_closed_with_diagnostics() -> None:
    transport = RecordingTransport(
        response={
            "id": "int_incomplete",
            "model": "gemini-3.8-flash",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "steps": [],
            "usage": {
                "total_input_tokens": 100,
                "total_output_tokens": 0,
                "total_thought_tokens": 512,
                "total_tokens": 612,
            },
        }
    )
    provider = GoogleGeminiProvider(api_key="test-secret", transport=transport)

    with pytest.raises(ModelProviderIncompleteError, match="interaction incomplete") as caught:
        _generate(provider)

    error = caught.value
    assert error.response_id == "int_incomplete"
    assert error.provider == "google"
    assert error.model == "gemini-3.8-flash"
    assert error.usage.input_tokens == 100
    assert error.usage.output_tokens == 0
    assert error.usage.thinking_tokens == 512
    assert error.usage.total_tokens == 612
    assert error.details["requested_max_output_tokens"] == 512
    assert error.details["incomplete_details"] == {"reason": "max_output_tokens"}


def test_invalid_service_tier_is_rejected() -> None:
    with pytest.raises(ValueError, match="service_tier"):
        GoogleGeminiProvider(api_key="test-secret", service_tier="unknown")


def test_missing_api_key_fails_closed() -> None:
    provider = GoogleGeminiProvider(api_key="")

    with pytest.raises(ModelProviderError, match="GEMINI_API_KEY"):
        provider.generate_structured(
            prompt="inspect",
            json_schema={"type": "object"},
            max_output_tokens=128,
            thinking_level="low",
        )
