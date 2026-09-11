from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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


class ModelProviderIncompleteError(ModelProviderError):
    """A provider completed a request but could not finish the requested output."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        response_id: str | None,
        usage: ModelUsage,
        details: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.response_id = response_id
        self.usage = usage
        self.details = details or {}


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


@runtime_checkable
class InputTokenCountingProvider(Protocol):
    """Optional provider capability for exact preflight input-token counting."""

    def count_input_tokens(self, text: str) -> int: ...
