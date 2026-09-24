from __future__ import annotations

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
class OpenRouterStructuredModelProvider:
    """Minimal provider-neutral structured-output client for OpenRouter."""

    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = 120.0
    structured_mode: StructuredMode = "json_schema"
    provider_order: tuple[str, ...] = ()
    allow_provider_fallbacks: bool = True
    max_structured_attempts: int = 2

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is required for live calls")
        if not self.model.strip():
            raise ValueError("OpenRouter model is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.structured_mode not in {"tool", "json_schema", "json_object"}:
            raise ValueError("unsupported structured_mode")
        if self.max_structured_attempts < 1 or self.max_structured_attempts > 3:
            raise ValueError("max_structured_attempts must be between 1 and 3")

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
        request_prompt = prompt
        if self.structured_mode == "json_object":
            request_prompt += (
                "\n\nReturn only one valid JSON object matching the requested "
                "fields. Do not include reasoning, Markdown, code fences, or prose "
                "outside the JSON object."
            )

        invalid_attempts: list[JsonObject] = []
        ignored_providers: list[str] = []
        aggregate_input: int | None = None
        aggregate_output: int | None = None
        aggregate_thinking: int | None = None
        aggregate_total: int | None = None
        aggregate_cost: float | None = None

        for attempt in range(1, self.max_structured_attempts + 1):
            payload: JsonObject = {
                "model": self.model,
                "messages": [{"role": "user", "content": request_prompt}],
                "max_tokens": max_output_tokens,
                "provider": self._provider_routing(
                    ignore_providers=tuple(ignored_providers)
                ),
                "usage": {"include": True},
            }
            self._apply_structured_output(payload=payload, json_schema=json_schema)
            if thinking_level and thinking_level != "none":
                payload["reasoning"] = {"effort": thinking_level}

            raw = self._post_payload(payload)
            body: dict[str, object] = {}
            usage_map: dict[str, object] = {}
            try:
                body = _json_object(raw)
                usage_map = _usage_map(body)
                aggregate_input = _add_optional_int(
                    aggregate_input, _int_or_none(usage_map.get("prompt_tokens"))
                )
                aggregate_output = _add_optional_int(
                    aggregate_output,
                    _int_or_none(usage_map.get("completion_tokens")),
                )
                aggregate_thinking = _add_optional_int(
                    aggregate_thinking,
                    _reasoning_tokens(usage_map),
                )
                aggregate_total = _add_optional_int(
                    aggregate_total, _int_or_none(usage_map.get("total_tokens"))
                )
                aggregate_cost = _add_optional_float(
                    aggregate_cost, _float_or_none(usage_map.get("cost"))
                )

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
                provider = str(body.get("provider") or "")
                invalid_attempts.append(
                    {
                        "attempt": attempt,
                        "routed_provider": provider,
                        "response_id": str(body.get("id") or ""),
                        "model": str(body.get("model") or self.model),
                        "error": str(exc)[:1000],
                        "cost_usd": _float_or_none(usage_map.get("cost")),
                    }
                )
                if (
                    provider
                    and self.allow_provider_fallbacks
                    and not self.provider_order
                    and provider not in ignored_providers
                ):
                    ignored_providers.append(provider)
                if attempt < self.max_structured_attempts:
                    continue
                raise ModelProviderError(
                    "OpenRouter returned invalid structured responses after "
                    f"{attempt} attempt(s) (mode={self.structured_mode}, "
                    f"providers={[item.get('routed_provider') for item in invalid_attempts]!r}): "
                    f"{exc}"
                ) from exc

            model = body.get("model")
            response_id = body.get("id")
            provider_raw = body.get("provider")
            provider_metadata: JsonObject = {
                "routed_provider": (
                    str(provider_raw) if provider_raw is not None else ""
                ),
                "requested_model": self.model,
                "structured_mode": self.structured_mode,
                "provider_order": list(self.provider_order),
                "allow_provider_fallbacks": self.allow_provider_fallbacks,
                "structured_attempt_count": attempt,
                "invalid_structured_attempts": invalid_attempts,
                "ignored_providers_on_retry": ignored_providers,
            }
            return StructuredGenerationResult(
                value=value,
                provider=self.provider_name,
                model=str(model or self.model),
                model_version=str(model) if model else None,
                response_id=str(response_id) if response_id else None,
                usage=ModelUsage(
                    input_tokens=aggregate_input,
                    output_tokens=aggregate_output,
                    thinking_tokens=aggregate_thinking,
                    total_tokens=aggregate_total,
                ),
                cost_usd=aggregate_cost,
                provider_metadata=provider_metadata,
            )

        raise AssertionError("structured-attempt loop terminated unexpectedly")

    def _post_payload(self, payload: JsonObject) -> bytes:
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
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise ModelProviderError(
                f"OpenRouter HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ModelProviderError(
                f"OpenRouter transport error: {exc.reason}"
            ) from exc

    def _provider_routing(
        self,
        *,
        ignore_providers: tuple[str, ...] = (),
    ) -> JsonObject:
        routing: JsonObject = {
            "require_parameters": True,
            "allow_fallbacks": self.allow_provider_fallbacks,
        }
        if self.provider_order:
            routing["order"] = list(self.provider_order)
        else:
            routing["sort"] = "price"
            if ignore_providers:
                routing["ignore"] = list(ignore_providers)
        return routing

    def _apply_structured_output(
        self,
        *,
        payload: JsonObject,
        json_schema: JsonObject,
    ) -> None:
        name = "jurisnexo_structured_output"
        if self.structured_mode == "tool":
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": "Return the structured JurisNexo result.",
                        "parameters": json_schema,
                    },
                }
            ]
            payload["tool_choice"] = "required"
            return
        if self.structured_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
            return
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": json_schema,
            },
        }


def _usage_map(body: dict[str, object]) -> dict[str, object]:
    usage_raw = body.get("usage")
    return (
        cast(dict[str, object], usage_raw)
        if isinstance(usage_raw, dict)
        else {}
    )


def _add_optional_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _add_optional_float(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


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
