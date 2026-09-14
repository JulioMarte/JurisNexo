from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, Literal, cast

from agents.items import ModelResponse
from pydantic import BaseModel

ProviderName = Literal["gemini", "deepseek"]
PricingBand = Literal["peak", "off_peak"]
ExecutionMode = Literal["realtime", "batch"]

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_cache_hit_per_million_usd: Decimal
    input_cache_miss_per_million_usd: Decimal
    output_per_million_usd: Decimal


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    provider: str
    model: str
    model_version: str
    effective_from_utc: datetime
    pricing_band: PricingBand
    execution_mode: ExecutionMode
    input_cache_hit_per_million_usd: Decimal
    input_cache_miss_per_million_usd: Decimal
    output_per_million_usd: Decimal
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "effective_from_utc": self.effective_from_utc.isoformat(),
            "pricing_band": self.pricing_band,
            "execution_mode": self.execution_mode,
            "input_cache_hit_per_million_usd": str(self.input_cache_hit_per_million_usd),
            "input_cache_miss_per_million_usd": str(self.input_cache_miss_per_million_usd),
            "output_per_million_usd": str(self.output_per_million_usd),
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ContextComposition:
    """Observable request composition in characters, not invented token attribution."""

    system_instruction_chars: int
    input_chars: int
    message_chars: int
    tool_result_chars: int
    reasoning_replay_chars: int
    tool_call_chars: int
    other_input_chars: int
    tool_schema_chars: int
    input_item_count: int

    @property
    def approximate_total_context_chars(self) -> int:
        return self.system_instruction_chars + self.input_chars + self.tool_schema_chars

    def as_dict(self) -> dict[str, int]:
        return {
            "system_instruction_chars": self.system_instruction_chars,
            "input_chars": self.input_chars,
            "message_chars": self.message_chars,
            "tool_result_chars": self.tool_result_chars,
            "reasoning_replay_chars": self.reasoning_replay_chars,
            "tool_call_chars": self.tool_call_chars,
            "other_input_chars": self.other_input_chars,
            "tool_schema_chars": self.tool_schema_chars,
            "input_item_count": self.input_item_count,
            "approximate_total_context_chars": self.approximate_total_context_chars,
        }


@dataclass(frozen=True, slots=True)
class ProviderObservabilityEvent:
    """Full provider-exposed reasoning plus request-shape metadata for debugging."""

    session_turn: int
    run_turn: int
    role: str
    round_number: int
    request_started_at: datetime
    response_completed_at: datetime
    provider: str
    model: str
    reasoning_text: str
    reasoning_sha256: str | None
    reasoning_char_count: int
    context_composition: ContextComposition
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int

    def as_dict(self) -> dict[str, object]:
        return {
            "session_turn": self.session_turn,
            "run_turn": self.run_turn,
            "role": self.role,
            "round_number": self.round_number,
            "request_started_at": self.request_started_at.isoformat(),
            "response_completed_at": self.response_completed_at.isoformat(),
            "provider": self.provider,
            "model": self.model,
            "reasoning_text": self.reasoning_text,
            "reasoning_sha256": self.reasoning_sha256,
            "reasoning_char_count": self.reasoning_char_count,
            "context_composition": self.context_composition.as_dict(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True, slots=True)
class ModelTurnUsage:
    session_turn: int
    run_turn: int
    role: str
    round_number: int
    request_started_at: datetime
    response_completed_at: datetime
    request_latency_seconds: float
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cache_hit_tokens: int
    input_cache_miss_tokens: int
    reasoning_tokens: int
    estimated_cost_usd: Decimal | None
    session_total_tokens_after_turn: int
    session_model_time_seconds_after_turn: float
    session_output_tokens_per_second_after_turn: float | None
    session_total_tokens_per_second_after_turn: float | None
    session_estimated_cost_usd_after_turn: Decimal | None
    pricing: PricingSnapshot | None
    response_id: str | None
    request_id: str | None
    provider_reasoning_char_count: int = 0
    provider_reasoning_sha256: str | None = None
    context_composition: ContextComposition | None = None

    @property
    def output_tokens_per_second(self) -> float | None:
        return _rate(self.output_tokens, self.request_latency_seconds)

    @property
    def total_tokens_per_second(self) -> float | None:
        return _rate(self.total_tokens, self.request_latency_seconds)

    def as_dict(self) -> dict[str, object]:
        return {
            "session_turn": self.session_turn,
            "run_turn": self.run_turn,
            "role": self.role,
            "round_number": self.round_number,
            "request_started_at": self.request_started_at.isoformat(),
            "response_completed_at": self.response_completed_at.isoformat(),
            "request_latency_seconds": self.request_latency_seconds,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cache_hit_tokens": self.input_cache_hit_tokens,
            "input_cache_miss_tokens": self.input_cache_miss_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "output_tokens_per_second": self.output_tokens_per_second,
            "total_tokens_per_second": self.total_tokens_per_second,
            "estimated_cost_usd": (
                str(self.estimated_cost_usd) if self.estimated_cost_usd is not None else None
            ),
            "session_total_tokens_after_turn": self.session_total_tokens_after_turn,
            "session_model_time_seconds_after_turn": self.session_model_time_seconds_after_turn,
            "session_output_tokens_per_second_after_turn": (
                self.session_output_tokens_per_second_after_turn
            ),
            "session_total_tokens_per_second_after_turn": (
                self.session_total_tokens_per_second_after_turn
            ),
            "session_estimated_cost_usd_after_turn": (
                str(self.session_estimated_cost_usd_after_turn)
                if self.session_estimated_cost_usd_after_turn is not None
                else None
            ),
            "pricing": self.pricing.as_dict() if self.pricing is not None else None,
            "response_id": self.response_id,
            "request_id": self.request_id,
            "provider_reasoning_char_count": self.provider_reasoning_char_count,
            "provider_reasoning_sha256": self.provider_reasoning_sha256,
            "context_composition": (
                self.context_composition.as_dict()
                if self.context_composition is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ModelUsageSummary:
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cache_hit_tokens: int
    input_cache_miss_tokens: int
    reasoning_tokens: int
    model_time_seconds: float
    output_tokens_per_second: float | None
    total_tokens_per_second: float | None
    estimated_cost_usd: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cache_hit_tokens": self.input_cache_hit_tokens,
            "input_cache_miss_tokens": self.input_cache_miss_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "model_time_seconds": self.model_time_seconds,
            "output_tokens_per_second": self.output_tokens_per_second,
            "total_tokens_per_second": self.total_tokens_per_second,
            "estimated_cost_usd": (
                str(self.estimated_cost_usd) if self.estimated_cost_usd is not None else None
            ),
        }


class UnsupportedPricingMode(ValueError):
    """Raised when no authoritative tariff exists for the requested execution mode."""


class DeepSeekPricingCatalog:
    """Versioned DeepSeek V4 public API pricing effective 2026-08-16 16:00 UTC."""

    source = "https://api-docs.deepseek.com/quick_start/pricing/"
    effective_from_utc = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)

    _MODEL_VERSIONS: dict[str, str] = {
        "deepseek-v4-flash": "DeepSeek-V4-Flash-0731",
        "deepseek-v4-pro": "DeepSeek-V4-Pro-0813",
    }
    _PEAK: dict[str, ModelPrice] = {
        "deepseek-v4-flash": ModelPrice(
            input_cache_hit_per_million_usd=Decimal("0.014"),
            input_cache_miss_per_million_usd=Decimal("0.44"),
            output_per_million_usd=Decimal("1.32"),
        ),
        "deepseek-v4-pro": ModelPrice(
            input_cache_hit_per_million_usd=Decimal("0.044"),
            input_cache_miss_per_million_usd=Decimal("1.32"),
            output_per_million_usd=Decimal("3.96"),
        ),
    }

    @staticmethod
    def pricing_band(at: datetime) -> PricingBand:
        at_utc = at.astimezone(UTC)
        if at_utc.weekday() >= 5:
            return "off_peak"
        clock = at_utc.time().replace(tzinfo=None)
        if time(1, 0) <= clock < time(4, 0) or time(6, 0) <= clock < time(10, 0):
            return "peak"
        return "off_peak"

    def snapshot(
        self,
        *,
        model: str,
        at: datetime,
        execution_mode: ExecutionMode = "realtime",
    ) -> PricingSnapshot:
        if execution_mode != "realtime":
            raise UnsupportedPricingMode(
                "DeepSeek has no documented discounted Batch API tariff; "
                "configure an authoritative batch price before using batch accounting"
            )
        if model not in self._PEAK:
            raise KeyError(f"no DeepSeek pricing registered for model {model!r}")
        if at.astimezone(UTC) < self.effective_from_utc:
            raise ValueError("pricing catalog does not cover requests before 2026-08-16 16:00 UTC")

        band = self.pricing_band(at)
        peak = self._PEAK[model]
        divisor = Decimal(1) if band == "peak" else Decimal(2)
        return PricingSnapshot(
            provider="deepseek",
            model=model,
            model_version=self._MODEL_VERSIONS[model],
            effective_from_utc=self.effective_from_utc,
            pricing_band=band,
            execution_mode=execution_mode,
            input_cache_hit_per_million_usd=peak.input_cache_hit_per_million_usd / divisor,
            input_cache_miss_per_million_usd=peak.input_cache_miss_per_million_usd / divisor,
            output_per_million_usd=peak.output_per_million_usd / divisor,
            source=self.source,
        )

    @staticmethod
    def cost_usd(
        *,
        pricing: PricingSnapshot,
        input_cache_hit_tokens: int,
        input_cache_miss_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        return (
            Decimal(input_cache_hit_tokens) * pricing.input_cache_hit_per_million_usd
            + Decimal(input_cache_miss_tokens) * pricing.input_cache_miss_per_million_usd
            + Decimal(output_tokens) * pricing.output_per_million_usd
        ) / _MILLION


def _int_field(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and value >= 0 else None


def _normalized_cached_tokens(response: ModelResponse) -> int:
    return max(response.usage.input_tokens_details.cached_tokens, 0)


def _normalized_reasoning_tokens(response: ModelResponse) -> int:
    return max(response.usage.output_tokens_details.reasoning_tokens, 0)


def _rate(tokens: int, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return tokens / seconds


def _as_object_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, BaseModel):
        return cast(dict[str, object], value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _json_char_count(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    payload: object = _as_object_dict(value) or value
    try:
        return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return len(str(payload))


def _item_type(value: object) -> str:
    payload = _as_object_dict(value)
    if payload is None:
        return ""
    item_type = payload.get("type")
    return item_type if isinstance(item_type, str) else ""


def summarize_request_context(
    *,
    system_instructions: str | None,
    input_value: str | list[object],
    tools: list[object],
) -> ContextComposition:
    """Describe observable request shape without pretending chars are provider token counts."""

    system_chars = len(system_instructions or "")
    items: list[object] = [input_value] if isinstance(input_value, str) else list(input_value)

    message_chars = 0
    tool_result_chars = 0
    reasoning_replay_chars = 0
    tool_call_chars = 0
    other_chars = 0
    input_chars = 0
    for item in items:
        chars = _json_char_count(item)
        input_chars += chars
        item_type = _item_type(item)
        if item_type == "reasoning":
            reasoning_replay_chars += chars
        elif item_type.endswith("_output") or item_type == "function_call_output":
            tool_result_chars += chars
        elif item_type in {"function_call", "custom_tool_call", "computer_call"}:
            tool_call_chars += chars
        elif item_type in {"message", "easy_input_message"} or isinstance(item, str):
            message_chars += chars
        else:
            other_chars += chars

    tool_schema_chars = sum(_json_char_count(tool) for tool in tools)
    return ContextComposition(
        system_instruction_chars=system_chars,
        input_chars=input_chars,
        message_chars=message_chars,
        tool_result_chars=tool_result_chars,
        reasoning_replay_chars=reasoning_replay_chars,
        tool_call_chars=tool_call_chars,
        other_input_chars=other_chars,
        tool_schema_chars=tool_schema_chars,
        input_item_count=len(items),
    )


def _text_from_nested_item(value: object) -> str | None:
    payload = _as_object_dict(value)
    if payload is None:
        return None
    text = payload.get("text")
    return text if isinstance(text, str) else None


def _provider_reasoning_text(response: ModelResponse) -> str:
    parts: list[str] = []
    for item in response.output:
        payload = _as_object_dict(item)
        if payload is None or payload.get("type") != "reasoning":
            continue
        for key in ("summary", "content"):
            nested = payload.get(key)
            if not isinstance(nested, list):
                continue
            for nested_item in cast(list[object], nested):
                text = _text_from_nested_item(nested_item)
                if isinstance(text, str) and text and text not in parts:
                    parts.append(text)
    return "\n".join(parts)


def _empty_turns() -> list[ModelTurnUsage]:
    return []


def _empty_observability_events() -> list[ProviderObservabilityEvent]:
    return []


@dataclass(slots=True)
class ModelUsageTracker:
    provider: ProviderName
    model: str
    execution_mode: ExecutionMode = "realtime"
    turns: list[ModelTurnUsage] = field(default_factory=_empty_turns)
    observability_events: list[ProviderObservabilityEvent] = field(
        default_factory=_empty_observability_events
    )
    _pricing: DeepSeekPricingCatalog = field(default_factory=DeepSeekPricingCatalog, repr=False)

    def record_response(
        self,
        *,
        role: str,
        round_number: int,
        run_turn: int,
        request_started_at: datetime,
        response: ModelResponse,
        context_composition: ContextComposition | None = None,
    ) -> ModelTurnUsage:
        response_completed_at = datetime.now(UTC)
        request_latency_seconds = max(
            (response_completed_at - request_started_at).total_seconds(),
            0.0,
        )
        raw = response.raw_usage if isinstance(response.raw_usage, dict) else {}
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens = response.usage.total_tokens
        cache_hit = _int_field(raw, "prompt_cache_hit_tokens")
        cache_miss = _int_field(raw, "prompt_cache_miss_tokens")
        if cache_hit is None:
            cache_hit = _normalized_cached_tokens(response)
        if cache_miss is None:
            cache_miss = max(input_tokens - cache_hit, 0)
        reasoning_tokens = _normalized_reasoning_tokens(response)
        reasoning_text = _provider_reasoning_text(response)
        reasoning_sha256 = (
            hashlib.sha256(reasoning_text.encode("utf-8")).hexdigest()
            if reasoning_text
            else None
        )

        pricing: PricingSnapshot | None = None
        estimated_cost: Decimal | None = None
        if self.provider == "deepseek":
            pricing = self._pricing.snapshot(
                model=self.model,
                at=request_started_at,
                execution_mode=self.execution_mode,
            )
            estimated_cost = self._pricing.cost_usd(
                pricing=pricing,
                input_cache_hit_tokens=cache_hit,
                input_cache_miss_tokens=cache_miss,
                output_tokens=output_tokens,
            )

        prior_total_tokens = sum(turn.total_tokens for turn in self.turns)
        prior_output_tokens = sum(turn.output_tokens for turn in self.turns)
        prior_model_time = sum(turn.request_latency_seconds for turn in self.turns)
        session_model_time = prior_model_time + request_latency_seconds
        prior_costs = [turn.estimated_cost_usd for turn in self.turns]
        if estimated_cost is not None and all(cost is not None for cost in prior_costs):
            session_cost: Decimal | None = sum(
                (cost for cost in prior_costs if cost is not None), Decimal(0)
            ) + estimated_cost
        else:
            session_cost = None

        session_turn = len(self.turns) + 1
        turn = ModelTurnUsage(
            session_turn=session_turn,
            run_turn=run_turn,
            role=role,
            round_number=round_number,
            request_started_at=request_started_at,
            response_completed_at=response_completed_at,
            request_latency_seconds=request_latency_seconds,
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            input_cache_hit_tokens=cache_hit,
            input_cache_miss_tokens=cache_miss,
            reasoning_tokens=reasoning_tokens,
            estimated_cost_usd=estimated_cost,
            session_total_tokens_after_turn=prior_total_tokens + total_tokens,
            session_model_time_seconds_after_turn=session_model_time,
            session_output_tokens_per_second_after_turn=_rate(
                prior_output_tokens + output_tokens,
                session_model_time,
            ),
            session_total_tokens_per_second_after_turn=_rate(
                prior_total_tokens + total_tokens,
                session_model_time,
            ),
            session_estimated_cost_usd_after_turn=session_cost,
            pricing=pricing,
            response_id=response.response_id,
            request_id=response.request_id,
            provider_reasoning_char_count=len(reasoning_text),
            provider_reasoning_sha256=reasoning_sha256,
            context_composition=context_composition,
        )
        self.turns.append(turn)
        if context_composition is not None:
            self.observability_events.append(
                ProviderObservabilityEvent(
                    session_turn=session_turn,
                    run_turn=run_turn,
                    role=role,
                    round_number=round_number,
                    request_started_at=request_started_at,
                    response_completed_at=response_completed_at,
                    provider=self.provider,
                    model=self.model,
                    reasoning_text=reasoning_text,
                    reasoning_sha256=reasoning_sha256,
                    reasoning_char_count=len(reasoning_text),
                    context_composition=context_composition,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    reasoning_tokens=reasoning_tokens,
                )
            )
        return turn

    def summary(self, turns: tuple[ModelTurnUsage, ...] | None = None) -> ModelUsageSummary:
        selected = turns if turns is not None else tuple(self.turns)
        costs = [turn.estimated_cost_usd for turn in selected]
        known_costs = [cost for cost in costs if cost is not None]
        estimated_cost = sum(known_costs, Decimal(0)) if len(known_costs) == len(costs) else None
        output_tokens = sum(turn.output_tokens for turn in selected)
        total_tokens = sum(turn.total_tokens for turn in selected)
        model_time_seconds = sum(turn.request_latency_seconds for turn in selected)
        return ModelUsageSummary(
            request_count=len(selected),
            input_tokens=sum(turn.input_tokens for turn in selected),
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            input_cache_hit_tokens=sum(turn.input_cache_hit_tokens for turn in selected),
            input_cache_miss_tokens=sum(turn.input_cache_miss_tokens for turn in selected),
            reasoning_tokens=sum(turn.reasoning_tokens for turn in selected),
            model_time_seconds=model_time_seconds,
            output_tokens_per_second=_rate(output_tokens, model_time_seconds),
            total_tokens_per_second=_rate(total_tokens, model_time_seconds),
            estimated_cost_usd=estimated_cost,
        )
