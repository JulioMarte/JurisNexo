from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelProviderError,
    ModelUsage,
    StructuredGenerationResult,
)


@dataclass(slots=True)
class OpenRouterStructuredModelProvider:
    """Minimal provider-neutral structured-output client for OpenRouter.

    This adapter intentionally depends only on the JurisNexo ModelProvider
    contract and the Python standard library. It is suitable for controlled
    normalization benchmarks and keeps SDK response types out of durable code.
    """

    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is required for live calls")
        if not self.model.strip():
            raise ValueError("OpenRouter model is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    @property
    def provider_name(self) -> str:
        return "openrouter"

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
        payload: JsonObject = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "jurisnexo_structured_output",
                    "strict": True,
                    "schema": json_schema,
                },
            },
            "provider": {"sort": "price", "require_parameters": True},
            "usage": {"include": True},
        }
        if thinking_level and thinking_level != "none":
            payload["reasoning"] = {"effort": thinking_level}

        request = Request(
            url=f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "JurisNexo normalization benchmark",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise ModelProviderError(
                f"OpenRouter HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ModelProviderError(f"OpenRouter transport error: {exc.reason}") from exc

        try:
            body = _json_object(raw)
            choices_raw = body["choices"]
            if not isinstance(choices_raw, list) or not choices_raw:
                raise TypeError("choices is not a non-empty list")
            choices = cast(list[object], choices_raw)
            choice = _json_object_value(choices[0], "choice")
            message = _json_object_value(choice["message"], "message")
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            value = cast(JsonObject, json.loads(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("OpenRouter returned an invalid structured response") from exc

        usage_raw = body.get("usage")
        usage_map = (
            cast(dict[str, object], usage_raw)
            if isinstance(usage_raw, dict)
            else {}
        )
        model = body.get("model")
        response_id = body.get("id")
        provider_raw = body.get("provider")
        return StructuredGenerationResult(
            value=value,
            provider=self.provider_name,
            model=str(model or self.model),
            model_version=str(model) if model else None,
            response_id=str(response_id) if response_id else None,
            usage=ModelUsage(
                input_tokens=_int_or_none(usage_map.get("prompt_tokens")),
                output_tokens=_int_or_none(usage_map.get("completion_tokens")),
                thinking_tokens=_reasoning_tokens(usage_map),
                total_tokens=_int_or_none(usage_map.get("total_tokens")),
            ),
            cost_usd=_float_or_none(usage_map.get("cost")),
            provider_metadata={
                "routed_provider": str(provider_raw) if provider_raw else "",
                "requested_model": self.model,
            },
        )


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _reasoning_tokens(usage: dict[str, object]) -> int | None:
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        return None
    typed_details = cast(dict[str, object], details)
    return _int_or_none(typed_details.get("reasoning_tokens"))


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _json_object(raw: bytes) -> dict[str, object]:
    loaded: object = json.loads(raw)
    return _json_object_value(loaded, "response")


def _json_object_value(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} is not an object")
    return cast(dict[str, object], value)
