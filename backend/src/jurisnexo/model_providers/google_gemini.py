from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
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
_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
_SERVICE_TIERS = frozenset({"flex", "standard", "priority"})


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
    service_tier: str = "flex"
    timeout_seconds: float = 900.0
    transport: JsonTransport | None = None
    max_attempts: int = 2
    retry_base_delay_seconds: float = 2.0
    retry_max_delay_seconds: float = 8.0
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must not be negative")
        if self.retry_max_delay_seconds < 0:
            raise ValueError("retry_max_delay_seconds must not be negative")
        if not self.model:
            raise ValueError("model must not be empty")
        if self.service_tier not in _SERVICE_TIERS:
            raise ValueError("service_tier must be flex, standard, or priority")

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def model_name(self) -> str:
        return self.model

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

        payload: JsonObject = {
            "model": self.model,
            "input": prompt,
            "service_tier": self.service_tier,
            "store": False,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": json_schema,
            },
            "generation_config": {
                "max_output_tokens": max_output_tokens,
                "thinking_level": thinking_level,
            },
        }
        response = self._post_with_retry(
            transport=self.transport or UrllibJsonTransport(),
            payload=payload,
        )
        return self._parse_interaction(response)

    def _post_with_retry(
        self,
        *,
        transport: JsonTransport,
        payload: JsonObject,
    ) -> JsonObject:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return transport.post_json(
                    url=_INTERACTIONS_ENDPOINT,
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

    def _parse_interaction(self, response: JsonObject) -> StructuredGenerationResult:
        status = response.get("status")
        if status != "completed":
            raise ModelProviderError(f"Gemini interaction did not complete; status={status!r}")

        text_parts: list[str] = []
        steps = response.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or step.get("type") != "model_output":
                    continue
                content = step.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)

        if not text_parts:
            raise ModelProviderError("Gemini interaction returned no model-output text")

        try:
            parsed_value: JsonValue = json.loads("".join(text_parts))
        except json.JSONDecodeError as exc:
            raise ModelProviderError("Gemini structured response is not valid JSON") from exc
        if not isinstance(parsed_value, dict):
            raise ModelProviderError("Gemini structured response must be a JSON object")

        response_model = response.get("model")
        effective_model = response_model if isinstance(response_model, str) else self.model
        response_id = response.get("id")
        return StructuredGenerationResult(
            value=cast(JsonObject, parsed_value),
            provider=self.provider_name,
            model=effective_model,
            model_version=None,
            response_id=response_id if isinstance(response_id, str) else None,
            usage=self._parse_usage(response.get("usage")),
        )

    @staticmethod
    def _parse_usage(raw: JsonValue) -> ModelUsage:
        if not isinstance(raw, dict):
            return ModelUsage()

        def integer(name: str) -> int | None:
            value = raw.get(name)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return ModelUsage(
            input_tokens=integer("total_input_tokens"),
            output_tokens=integer("total_output_tokens"),
            thinking_tokens=integer("total_thought_tokens"),
            total_tokens=integer("total_tokens"),
        )
