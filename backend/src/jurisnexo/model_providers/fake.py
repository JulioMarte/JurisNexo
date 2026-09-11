from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelUsage,
    StructuredGenerationResult,
)


@dataclass(slots=True)
class FakeModelProvider:
    response: JsonObject
    model: str = "fake-model"

    @property
    def provider_name(self) -> str:
        return "fake"

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
        del prompt, json_schema, max_output_tokens, thinking_level
        return StructuredGenerationResult(
            value=self.response,
            provider=self.provider_name,
            model=self.model,
            model_version="test",
            response_id="fake-response",
            usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )
