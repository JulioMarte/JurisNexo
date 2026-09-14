from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from agents import ModelRetrySettings, ModelSettings, retry_policies
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.models.interface import Model, ModelProvider, ModelTracing
from agents.tool import Tool
from openai.types.responses import ResponsePromptParam

from jurisnexo.model_providers.usage_accounting import (
    ModelUsageTracker,
    summarize_request_context,
)

_DEFAULT_STAGE_RUNTIME_SECONDS = 600.0
_DEFAULT_MODEL_ATTEMPT_TIMEOUT_SECONDS = 90.0
_DEFAULT_SOFT_DEADLINE_FRACTION = 0.80
_FINALIZATION_WINDOW_SECONDS = 60.0


def _model_retry_settings() -> ModelRetrySettings:
    """Retry only transient/replay-safe model failures with bounded backoff."""

    return ModelRetrySettings(
        max_retries=2,
        backoff={
            "initial_delay": 0.5,
            "max_delay": 4.0,
            "multiplier": 2.0,
            "jitter": True,
        },
        policy=retry_policies.any(
            retry_policies.provider_suggested(),
            retry_policies.retry_after(),
            retry_policies.network_error(),
            retry_policies.http_status([408, 409, 429, 500, 502, 503, 504]),
        ),
    )


@dataclass(frozen=True, slots=True)
class UsageScope:
    role: str
    round_number: int
    started_monotonic: float | None = None
    runtime_budget_seconds: float | None = None
    soft_deadline_fraction: float = _DEFAULT_SOFT_DEADLINE_FRACTION

    def __post_init__(self) -> None:
        if self.round_number < 0:
            raise ValueError("round_number must be non-negative")
        if self.runtime_budget_seconds is not None and self.runtime_budget_seconds <= 0:
            raise ValueError("runtime_budget_seconds must be positive")
        if not 0 < self.soft_deadline_fraction < 1:
            raise ValueError("soft_deadline_fraction must be between 0 and 1")

    def runtime_status(self, *, now_monotonic: float | None = None) -> str | None:
        if self.started_monotonic is None or self.runtime_budget_seconds is None:
            return None
        now = time.monotonic() if now_monotonic is None else now_monotonic
        elapsed = max(now - self.started_monotonic, 0.0)
        remaining = max(self.runtime_budget_seconds - elapsed, 0.0)
        soft_at = self.runtime_budget_seconds * self.soft_deadline_fraction
        soft_remaining = max(soft_at - elapsed, 0.0)

        if remaining <= _FINALIZATION_WINDOW_SECONDS:
            guidance = (
                "FINALIZATION_WINDOW: use the evidence already gathered and finalize now. Do not "
                "start optional exploration. If a material uncertainty cannot be resolved safely "
                "inside the remaining window, encode it explicitly instead of guessing."
            )
        elif elapsed >= soft_at:
            guidance = (
                "SOFT_DEADLINE_ACTIVE: stop broad exploration. Resolve only a still-blocking "
                "material uncertainty that can change routing/approval; otherwise finalize from "
                "the evidence already gathered, preserving explicit unknowns."
            )
        else:
            guidance = (
                "INVESTIGATION_WINDOW: continue only on material uncertainties. Plan to finish "
                "before the soft deadline; the hard deadline is an infrastructure fuse, not a "
                "target or a reason to rush unsupported conclusions."
            )

        return (
            "RUNTIME_BUDGET_STATUS\n"
            f"stage_role={self.role}\n"
            f"elapsed_seconds={elapsed:.1f}\n"
            f"hard_remaining_seconds={remaining:.1f}\n"
            f"soft_deadline_remaining_seconds={soft_remaining:.1f}\n"
            f"{guidance}"
        )


def _with_runtime_status(system_instructions: str | None, scope: UsageScope) -> str | None:
    status = scope.runtime_status()
    if status is None:
        return system_instructions
    if system_instructions:
        return f"{system_instructions}\n\n# Runtime budget\n{status}"
    return f"# Runtime budget\n{status}"


def bounded_model_settings(model_settings: ModelSettings) -> ModelSettings:
    """Apply shared per-attempt timeout/retry policy without changing agent reasoning budgets."""

    return model_settings.resolve(
        {
            "preserve_raw_usage": True,
            "timeout": _DEFAULT_MODEL_ATTEMPT_TIMEOUT_SECONDS,
            "retry": _model_retry_settings(),
        }
    )


class UsageTrackingModel(Model):
    """Model wrapper adding usage accounting, bounded retries, and deadline awareness."""

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
        effective_system_instructions = _with_runtime_status(system_instructions, self._scope)
        context_composition = summarize_request_context(
            system_instructions=effective_system_instructions,
            input_value=(
                input if isinstance(input, str) else cast(list[object], input)
            ),
            tools=cast(list[object], tools),
        )
        settings = bounded_model_settings(model_settings)
        response = await self._inner.get_response(
            effective_system_instructions,
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
            context_composition=context_composition,
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
        effective_system_instructions = _with_runtime_status(system_instructions, self._scope)
        settings = bounded_model_settings(model_settings).resolve({"include_usage": True})
        return self._inner.stream_response(
            effective_system_instructions,
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

    def set_scope(
        self,
        *,
        role: str,
        round_number: int,
        runtime_budget_seconds: float = _DEFAULT_STAGE_RUNTIME_SECONDS,
        soft_deadline_fraction: float = _DEFAULT_SOFT_DEADLINE_FRACTION,
    ) -> None:
        self._scope = UsageScope(
            role=role,
            round_number=round_number,
            started_monotonic=time.monotonic(),
            runtime_budget_seconds=runtime_budget_seconds,
            soft_deadline_fraction=soft_deadline_fraction,
        )

    def get_model(self, model_name: str | None) -> Model:
        return UsageTrackingModel(
            inner=self._inner.get_model(model_name),
            tracker=self.tracker,
            scope=self._scope,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
