from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.decisions import (
    DecisionQuestion,
    DecisionResult,
    DecisionUsage,
)


@dataclass(slots=True)
class OpenRouterDecisionProvider:
    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/alpha"
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is required for live calls")
        if not self.model.strip():
            raise ValueError("OpenRouter decision model is required")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def model_name(self) -> str:
        return self.model

    def decide(
        self,
        *,
        state_description: str,
        records: tuple[dict[str, str], ...],
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResult:
        if not state_description.strip():
            raise ValueError("state_description must not be empty")
        if not records:
            raise ValueError("at least one decision record is required")
        if not questions:
            raise ValueError("at least one decision question is required")

        payload = {
            "model": self.model,
            "state": {
                "description": state_description,
                "records": list(records),
            },
            "questions": questions,
        }
        request = Request(
            url=f"{self.base_url.rstrip('/')}/decisions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "JurisNexo decision benchmark",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise ModelProviderError(
                f"OpenRouter decisions HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ModelProviderError(
                f"OpenRouter decisions transport error: {exc.reason}"
            ) from exc

        try:
            body = cast(dict[str, Any], json.loads(raw))
            answers_raw = body["answers"]
            if not isinstance(answers_raw, dict):
                raise TypeError("answers is not an object")
            answers = {
                str(key): cast(dict[str, Any], value)
                for key, value in answers_raw.items()
                if isinstance(value, dict)
            }
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(
                "OpenRouter decisions returned an invalid response"
            ) from exc

        usage_raw = body.get("usage")
        usage = usage_raw if isinstance(usage_raw, dict) else {}
        effective_model = str(body.get("model") or self.model)
        response_id = body.get("id")
        return DecisionResult(
            answers=answers,
            provider=self.provider_name,
            model=effective_model,
            model_version=effective_model,
            response_id=str(response_id) if response_id else None,
            usage=DecisionUsage(
                input_tokens=_int_or_none(usage.get("prompt_tokens")),
                output_tokens=_int_or_none(usage.get("completion_tokens")),
                total_tokens=_int_or_none(usage.get("total_tokens")),
            ),
            cost_usd=_float_or_none(usage.get("cost")),
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
