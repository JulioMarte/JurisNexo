from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class StructuredGenerationResult:
    value: JsonObject
    provider: str
    model: str
    model_version: str | None
    response_id: str | None
    usage: ModelUsage


class ModelProviderError(RuntimeError):
    """Raised when a model provider cannot return a valid structured response."""


class ModelProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate_structured(
        self,
        *,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
        thinking_level: str,
    ) -> StructuredGenerationResult: ...
