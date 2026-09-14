from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from agents import ModelSettings
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelProvider, ModelTracing
from agents.tool import Tool
from openai.types.responses import ResponsePromptParam

from jurisnexo.model_providers.usage_accounting import ModelUsageTracker


@dataclass(frozen=True, slots=True)
class UsageScope:
    role: str
    round_number: int


class UsageTrackingModel(Model):
    """Transparent non-streaming Model wrapper that records one usage row per LLM request."""

    def __init__(
        self,
        *,
        inner: Model,
        tracker: ModelUsageTracker,
        scope: UsageScope,
    ) -> None:
        self._inner = inner
        self._tracker = tracker
        self._scope = scope
        self._run_turn = 0

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        started_at = datetime.now(UTC)
        settings = model_settings.resolve({"preserve_raw_usage": True})
        response = await self._inner.get_response(
            system_instructions,
            input,
            settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )
        self._run_turn += 1
        self._tracker.record_response(
            role=self._scope.role,
            round_number=self._scope.round_number,
            run_turn=self._run_turn,
            request_started_at=started_at,
            response=response,
        )
        return response

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        # JurisNexo structure ingestion deliberately uses Runner.run, not run_streamed.
        # Preserve raw usage if a future caller streams, but do not pretend we can
        # account a turn until a terminal ModelResponse is available.
        settings = model_settings.resolve({"preserve_raw_usage": True, "include_usage": True})
        return self._inner.stream_response(
            system_instructions,
            input,
            settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    async def close(self) -> None:
        await self._inner.close()


class UsageTrackingModelProvider(ModelProvider):
    """Provider wrapper whose scope is rebound before each sequential agent stage."""

    def __init__(self, *, inner: ModelProvider, tracker: ModelUsageTracker) -> None:
        self._inner = inner
        self.tracker = tracker
        self._scope = UsageScope(role="unscoped", round_number=0)

    def set_scope(self, *, role: str, round_number: int) -> None:
        if round_number < 0:
            raise ValueError("round_number must be non-negative")
        self._scope = UsageScope(role=role, round_number=round_number)

    def get_model(self, model_name: str | None) -> Model:
        return UsageTrackingModel(
            inner=self._inner.get_model(model_name),
            tracker=self.tracker,
            scope=self._scope,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
