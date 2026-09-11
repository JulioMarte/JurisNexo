from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jurisnexo.model_providers.contracts import (
    JsonObject,
    JsonValue,
    ModelProviderError,
    ModelUsage,
    StructuredGenerationResult,
)

_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})


def _default_fallback_models() -> tuple[str, ...]:
    return ("gemini-3.7-flash",)


class GeminiTransportError(ModelProviderError):
    """Transport-level Gemini failure with explicit retry semantics."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class JsonTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject: ...


@dataclass(slots=True)
class UrllibJsonTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        body = json.dumps(payload).encode("utf-8")
        request = Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GeminiTransportError(
                f"Gemini HTTP error {exc.code}: {detail[:500]}",
                retryable=exc.code in _RETRYABLE_HTTP_STATUS,
            ) from exc
        except URLError as exc:
            raise GeminiTransportError(
                f"Gemini network error: {exc.reason}",
                retryable=True,
            ) from exc

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ModelProviderError("Gemini returned a non-object JSON response")
        return cast(JsonObject, parsed)


@dataclass(slots=True)
class GoogleGeminiProvider:
    api_key: str
    model: str = "gemini-3.8-flash"
    timeout_seconds: float = 90.0
    transport: JsonTransport | None = None
    max_attempts: int = 2
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 4.0
    fallback_models: tuple[str, ...] = field(default_factory=_default_fallback_models)
    sleep: Callable[[float], None] = time.sleep
    active_model: str = field(init=False)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must not be negative")
        if self.retry_max_delay_seconds < 0:
            raise ValueError("retry_max_delay_seconds must not be negative")
        if not self.model:
            raise ValueError("model must not be empty")
        if any(not model for model in self.fallback_models):
            raise ValueError("fallback models must not be empty")
        self.active_model = self.model

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self.active_model

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult:
        if not self.api_key:
            raise ModelProviderError("GEMINI_API_KEY is required")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if thinking_level not in {"low", "medium", "high"}:
            raise ValueError("thinking_level must be low, medium, or high")

        transport = self.transport or UrllibJsonTransport()
        payload: JsonObject = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": json_schema,
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingLevel": thinking_level},
            },
        }
        last_transient_error: GeminiTransportError | None = None
        for candidate_model in self._candidate_models():
            endpoint = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{candidate_model}:generateContent"
            )
            try:
                response = self._post_with_retry(
                    transport=transport,
                    endpoint=endpoint,
                    payload=payload,
                )
            except GeminiTransportError as exc:
                if not exc.retryable:
                    raise
                last_transient_error = exc
                continue

            self.active_model = candidate_model
            return self._parse_response(response, effective_model=candidate_model)

        if last_transient_error is not None:
            raise last_transient_error
        raise AssertionError("Gemini model failover loop exited unexpectedly")

    def _candidate_models(self) -> tuple[str, ...]:
        ordered = (self.active_model, self.model, *self.fallback_models)
        return tuple(dict.fromkeys(ordered))

    def _post_with_retry(
        self,
        *,
        transport: JsonTransport,
        endpoint: str,
        payload: JsonObject,
    ) -> JsonObject:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return transport.post_json(
                    url=endpoint,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key,
                    },
                    payload=payload,
                    timeout_seconds=self.timeout_seconds,
                )
            except GeminiTransportError as exc:
                if not exc.retryable or attempt >= self.max_attempts:
                    raise
                delay = min(
                    self.retry_base_delay_seconds * (2 ** (attempt - 1)),
                    self.retry_max_delay_seconds,
                )
                self.sleep(delay)

        raise AssertionError("Gemini retry loop exited unexpectedly")

    def _parse_response(
        self,
        response: JsonObject,
        *,
        effective_model: str,
    ) -> StructuredGenerationResult:
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            prompt_feedback = response.get("promptFeedback")
            raise ModelProviderError(
                f"Gemini returned no candidates; prompt feedback={prompt_feedback!r}"
            )

        first = candidates[0]
        if not isinstance(first, dict):
            raise ModelProviderError("Gemini candidate has unexpected shape")
        content = first.get("content")
        if not isinstance(content, dict):
            raise ModelProviderError("Gemini candidate has no content")
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
            raise ModelProviderError("Gemini candidate has no text part")
        text = parts[0].get("text")
        if not isinstance(text, str):
            raise ModelProviderError("Gemini candidate text is missing")

        try:
            parsed_value: JsonValue = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelProviderError("Gemini structured response is not valid JSON") from exc
        if not isinstance(parsed_value, dict):
            raise ModelProviderError("Gemini structured response must be a JSON object")

        usage_raw = response.get("usageMetadata")
        usage = self._parse_usage(usage_raw)
        model_version = response.get("modelVersion")
        response_id = response.get("responseId")
        return StructuredGenerationResult(
            value=cast(JsonObject, parsed_value),
            provider=self.provider_name,
            model=effective_model,
            model_version=model_version if isinstance(model_version, str) else None,
            response_id=response_id if isinstance(response_id, str) else None,
            usage=usage,
        )

    @staticmethod
    def _parse_usage(raw: JsonValue) -> ModelUsage:
        if not isinstance(raw, dict):
            return ModelUsage()

        def integer(name: str) -> int | None:
            value = raw.get(name)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return ModelUsage(
            input_tokens=integer("promptTokenCount"),
            output_tokens=integer("candidatesTokenCount"),
            thinking_tokens=integer("thoughtsTokenCount"),
            total_tokens=integer("totalTokenCount"),
        )
