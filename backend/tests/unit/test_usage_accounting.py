from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from jurisnexo.model_providers.usage_accounting import (
    DeepSeekPricingCatalog,
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
