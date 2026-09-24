from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Literal, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jurisnexo.model_providers.chat_message import (
    extract_structured_object,
    validate_structured_object,
)
from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelProviderError,
    ModelUsage,
    StructuredGenerationResult,
)

StructuredMode = Literal["tool", "json_schema", "json_object"]


@dataclass(slots=True)
class OpenRouterVisualModelProvider:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = 120.0
    reasoning_effort: str = "high"
    structured_mode: StructuredMode = "tool"
    provider_order: tuple[str, ...] = ()
    allow_provider_fallbacks: bool = True

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is required for live calls")
        if not self.model.strip():
            raise ValueError("visual model is required")
        if self.reasoning_effort not in {"none", "high", "xhigh"}:
            raise ValueError(
                "visual reasoning_effort must be none, high or xhigh"
            )
        if self.structured_mode not in {"tool", "json_schema", "json_object"}:
            raise ValueError("unsupported visual structured_mode")

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
        request_prompt = prompt
        payload: JsonObject = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request_prompt},
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
            "provider": self._provider_routing(),
            "usage": {"include": True},
        }
        self._apply_structured_output(
            payload=payload,
            json_schema=json_schema,
        )
        if self.reasoning_effort != "none":
            payload["reasoning"] = {"effort": self.reasoning_effort}
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

        body: dict[str, object] = {}
        try:
            body = _json_object(raw)
            choices_raw = body["choices"]
            if not isinstance(choices_raw, list) or not choices_raw:
                raise TypeError("choices is not a non-empty list")
            choices = cast(list[object], choices_raw)
            choice = _json_object_value(choices[0], "choice")
            message = _json_object_value(choice["message"], "message")
            value = extract_structured_object(message)
            validate_structured_object(value, json_schema)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            provider = body.get("provider")
            raise ModelProviderError(
                "OpenRouter returned an invalid visual structured response "
                f"(mode={self.structured_mode}, provider={provider!r}): {exc}"
            ) from exc

        usage_raw = body.get("usage")
        usage = (
            cast(dict[str, object], usage_raw)
            if isinstance(usage_raw, dict)
            else {}
        )
        model = str(body.get("model") or self.model)
        response_id = body.get("id")
        routed_provider = body.get("provider")
        return StructuredGenerationResult(
            value=value,
            provider="openrouter",
            model=model,
            model_version=model,
            response_id=str(response_id) if response_id else None,
            usage=ModelUsage(
                input_tokens=_int_or_none(usage.get("prompt_tokens")),
                output_tokens=_int_or_none(usage.get("completion_tokens")),
                thinking_tokens=_reasoning_tokens(usage),
                total_tokens=_int_or_none(usage.get("total_tokens")),
            ),
            cost_usd=_float_or_none(usage.get("cost")),
            provider_metadata={
                "requested_model": self.model,
                "requested_reasoning_effort": self.reasoning_effort,
                "structured_mode": self.structured_mode,
                "routed_provider": (
                    str(routed_provider) if routed_provider is not None else ""
                ),
                "provider_order": list(self.provider_order),
                "allow_provider_fallbacks": self.allow_provider_fallbacks,
            },
        )

    def _provider_routing(self) -> JsonObject:
        routing: JsonObject = {
            "require_parameters": True,
            "allow_fallbacks": self.allow_provider_fallbacks,
        }
        if self.provider_order:
            routing["order"] = list(self.provider_order)
        else:
            routing["sort"] = "price"
        return routing

    def _apply_structured_output(
        self,
        *,
        payload: JsonObject,
        json_schema: JsonObject,
    ) -> None:
        name = "jurisnexo_visual_verification"
        if self.structured_mode == "tool":
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            "Return the visual transcription verification result."
                        ),
                        "parameters": json_schema,
                    },
                }
            ]
            # With exactly one tool, "required" is sufficient and is more
            # portable across OpenRouter providers than forcing a named tool.
            payload["tool_choice"] = "required"
            return
        if self.structured_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
            messages = cast(list[dict[str, object]], payload["messages"])
            content = cast(list[dict[str, object]], messages[0]["content"])
            text_part = content[0]
            original = str(text_part.get("text") or "")
            text_part["text"] = (
                original
                + "\n\nReturn only one valid JSON object. Do not include "
                "reasoning, Markdown, code fences, or prose outside the JSON."
            )
            return
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": json_schema,
            },
        }


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
