from __future__ import annotations

import pytest
from agents import ModelSettings

from jurisnexo.model_providers.agents_sdk_usage_provider import (
    UsageScope,
    bounded_model_settings,
)

pytestmark = pytest.mark.unit


def test_runtime_status_exposes_hard_and_soft_remaining_time() -> None:
    scope = UsageScope(
        role="structure_agent",
        round_number=0,
        started_monotonic=100.0,
        runtime_budget_seconds=600.0,
        soft_deadline_fraction=0.80,
    )

    status = scope.runtime_status(now_monotonic=220.0)

    assert status is not None
    assert "elapsed_seconds=120.0" in status
    assert "hard_remaining_seconds=480.0" in status
    assert "soft_deadline_remaining_seconds=360.0" in status
    assert "INVESTIGATION_WINDOW" in status


def test_runtime_status_switches_to_soft_deadline_without_forcing_guesswork() -> None:
    scope = UsageScope(
        role="structure_auditor",
        round_number=1,
        started_monotonic=100.0,
        runtime_budget_seconds=600.0,
        soft_deadline_fraction=0.80,
    )

    status = scope.runtime_status(now_monotonic=590.0)

    assert status is not None
    assert "SOFT_DEADLINE_ACTIVE" in status
    assert "explicit unknowns" in status


def test_runtime_status_reserves_finalization_window() -> None:
    scope = UsageScope(
        role="structure_agent",
        round_number=0,
        started_monotonic=100.0,
        runtime_budget_seconds=600.0,
    )

    status = scope.runtime_status(now_monotonic=650.0)

    assert status is not None
    assert "hard_remaining_seconds=50.0" in status
    assert "FINALIZATION_WINDOW" in status
    assert "instead of guessing" in status


def test_model_attempt_policy_is_shorter_than_stage_budget_and_retry_safe() -> None:
    settings = bounded_model_settings(ModelSettings(parallel_tool_calls=False))

    assert settings.parallel_tool_calls is False
    assert settings.timeout == 90.0
    assert settings.retry is not None
    assert settings.retry.max_retries == 2
    assert settings.retry.policy is not None


def test_runtime_scope_rejects_invalid_budget_configuration() -> None:
    with pytest.raises(ValueError, match="runtime_budget_seconds"):
        UsageScope(
            role="structure_agent",
            round_number=0,
            started_monotonic=100.0,
            runtime_budget_seconds=0.0,
        )

    with pytest.raises(ValueError, match="soft_deadline_fraction"):
        UsageScope(
            role="structure_agent",
            round_number=0,
            started_monotonic=100.0,
            runtime_budget_seconds=600.0,
            soft_deadline_fraction=1.0,
        )
