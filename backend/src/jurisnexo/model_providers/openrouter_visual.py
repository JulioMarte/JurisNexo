from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelProviderError,
    ModelUsage,
    StructuredGenerationResult,
)


@dataclass(slots=True)
class OpenRouterVisualModelProvider:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is required for live calls")
        if not self.model.strip():
            raise ValueError("visual model is required")

    def verify_image_text(
        self,
        *,
        image: bytes,
        media_type: str,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
    ) -> StructuredGenerationResult:
        encoded = base64.b64encode(image).decode("ascii")
        payload: JsonObject = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{encoded}",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "jurisnexo_visual_verification",
                    "strict": True,
                    "schema": json_schema,
                },
            },
            "provider": {"sort": "price", "require_parameters": True},
            "usage": {"include": True},
        }
        request = Request(
            url=f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "JurisNexo visual verification",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            raise ModelProviderError(
                f"OpenRouter visual HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ModelProviderError(
                f"OpenRouter visual transport error: {exc.reason}"
            ) from exc

        try:
            body = cast(dict[str, Any], json.loads(raw))
            choices = cast(list[dict[str, Any]], body["choices"])
            message = cast(dict[str, Any], choices[0]["message"])
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            value = cast(JsonObject, json.loads(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(
                "OpenRouter returned an invalid visual structured response"
            ) from exc

        usage_raw = body.get("usage")
        usage = usage_raw if isinstance(usage_raw, dict) else {}
        model = str(body.get("model") or self.model)
        response_id = body.get("id")
        return StructuredGenerationResult(
            value=value,
            provider="openrouter",
            model=model,
            model_version=model,
            response_id=str(response_id) if response_id else None,
            usage=ModelUsage(
                input_tokens=_int_or_none(usage.get("prompt_tokens")),
                output_tokens=_int_or_none(usage.get("completion_tokens")),
                total_tokens=_int_or_none(usage.get("total_tokens")),
            ),
            cost_usd=_float_or_none(usage.get("cost")),
            provider_metadata={"requested_model": self.model},
        )


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
