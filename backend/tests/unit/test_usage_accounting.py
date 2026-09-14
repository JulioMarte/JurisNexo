from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from jurisnexo.model_providers.usage_accounting import (
    DeepSeekPricingCatalog,
    ModelTurnUsage,
    ModelUsageTracker,
    UnsupportedPricingMode,
)

pytestmark = [pytest.mark.unit]


def test_deepseek_v4_flash_peak_and_off_peak_prices_are_versioned() -> None:
    catalog = DeepSeekPricingCatalog()
    peak = catalog.snapshot(
        model="deepseek-v4-flash",
        at=datetime(2026, 9, 14, 2, 30, tzinfo=UTC),  # Monday peak window.
    )
    off_peak = catalog.snapshot(
        model="deepseek-v4-flash",
        at=datetime(2026, 9, 14, 4, 30, tzinfo=UTC),
    )

    assert peak.model_version == "DeepSeek-V4-Flash-0731"
    assert peak.pricing_band == "peak"
    assert peak.input_cache_hit_per_million_usd == Decimal("0.014")
    assert peak.input_cache_miss_per_million_usd == Decimal("0.44")
    assert peak.output_per_million_usd == Decimal("1.32")
    assert off_peak.pricing_band == "off_peak"
    assert off_peak.input_cache_hit_per_million_usd == Decimal("0.007")
    assert off_peak.input_cache_miss_per_million_usd == Decimal("0.22")
    assert off_peak.output_per_million_usd == Decimal("0.66")


def test_deepseek_flash_cost_separates_cache_hits_misses_and_output() -> None:
    catalog = DeepSeekPricingCatalog()
    pricing = catalog.snapshot(
        model="deepseek-v4-flash",
        at=datetime(2026, 9, 14, 4, 30, tzinfo=UTC),
    )

    cost = catalog.cost_usd(
        pricing=pricing,
        input_cache_hit_tokens=1_000_000,
        input_cache_miss_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert cost == Decimal("0.887")


def test_weekends_are_always_off_peak() -> None:
    catalog = DeepSeekPricingCatalog()
    saturday = catalog.snapshot(
        model="deepseek-v4-flash",
        at=datetime(2026, 9, 19, 2, 30, tzinfo=UTC),
    )
    assert saturday.pricing_band == "off_peak"


def test_batch_pricing_fails_closed_until_deepseek_publishes_a_tariff() -> None:
    catalog = DeepSeekPricingCatalog()
    with pytest.raises(UnsupportedPricingMode, match="no documented discounted Batch API tariff"):
        catalog.snapshot(
            model="deepseek-v4-flash",
            at=datetime(2026, 9, 14, 4, 30, tzinfo=UTC),
            execution_mode="batch",
        )


def _turn(
    *,
    session_turn: int,
    seconds: float,
    output_tokens: int,
    total_tokens: int,
) -> ModelTurnUsage:
    started = datetime(2026, 9, 14, 4, 30, tzinfo=UTC) + timedelta(seconds=session_turn * 20)
    return ModelTurnUsage(
        session_turn=session_turn,
        run_turn=session_turn,
        role="structure_agent",
        round_number=0,
        request_started_at=started,
        response_completed_at=started + timedelta(seconds=seconds),
        provider="deepseek",
        model="deepseek-v4-flash",
        input_tokens=total_tokens - output_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_cache_hit_tokens=0,
        input_cache_miss_tokens=total_tokens - output_tokens,
        reasoning_tokens=0,
        estimated_cost_usd=None,
        session_total_tokens_after_turn=total_tokens,
        session_estimated_cost_usd_after_turn=None,
        pricing=None,
        response_id=None,
        request_id=None,
        session_model_time_seconds_after_turn=seconds,
        session_output_tokens_per_second_after_turn=output_tokens / seconds,
        session_total_tokens_per_second_after_turn=total_tokens / seconds,
    )


def test_turn_throughput_is_derived_from_tokens_and_request_latency() -> None:
    turn = _turn(session_turn=1, seconds=4.0, output_tokens=200, total_tokens=1000)

    assert turn.request_latency_seconds == 4.0
    assert turn.output_tokens_per_second == pytest.approx(50.0)
    assert turn.total_tokens_per_second == pytest.approx(250.0)
    assert turn.as_dict()["output_tokens_per_second"] == pytest.approx(50.0)


def test_session_throughput_is_weighted_by_model_time_not_mean_of_turn_rates() -> None:
    tracker = ModelUsageTracker(provider="deepseek", model="deepseek-v4-flash")
    turns = (
        _turn(session_turn=1, seconds=1.0, output_tokens=100, total_tokens=200),
        _turn(session_turn=2, seconds=9.0, output_tokens=90, total_tokens=900),
    )

    summary = tracker.summary(turns)

    assert summary.model_time_seconds == 10.0
    assert summary.output_tokens == 190
    assert summary.total_tokens == 1100
    assert summary.output_tokens_per_second == pytest.approx(19.0)
    assert summary.total_tokens_per_second == pytest.approx(110.0)
    assert summary.output_tokens_per_second != pytest.approx((100.0 + 10.0) / 2)
