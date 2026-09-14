# pyright: reportPrivateUsage=false
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from agents.exceptions import ModelBehaviorError

from jurisnexo.ingestion.sdk_extraction_agent import (
    _extraction_finalization_error_feedback,
)
from jurisnexo.ingestion.sdk_extraction_auditor import (
    _extraction_audit_finalization_error_feedback,
)

pytestmark = [pytest.mark.unit]


def _wrapper(*, max_attempts: int = 3) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            context=SimpleNamespace(
                finalization_errors=[],
                max_finalization_repair_attempts=max_attempts,
            )
        ),
    )


def test_extraction_finalization_returns_repair_feedback() -> None:
    wrapper = _wrapper()
    error = ModelBehaviorError("Invalid JSON input for tool finalize_extraction_annotations")

    feedback = _extraction_finalization_error_feedback(wrapper, error)

    assert "FINALIZATION_REJECTED" in feedback
    assert "DO NOT repeat page reads or searches" in feedback
    assert "Repair attempt 1 of 3" in feedback


def test_extraction_finalization_repair_is_bounded() -> None:
    wrapper = _wrapper(max_attempts=2)
    error = ModelBehaviorError("bad extraction payload")

    _extraction_finalization_error_feedback(wrapper, error)
    with pytest.raises(ModelBehaviorError, match="bad extraction payload"):
        _extraction_finalization_error_feedback(wrapper, error)


def test_extraction_audit_finalization_returns_repair_feedback() -> None:
    wrapper = _wrapper()
    error = ModelBehaviorError("Invalid source evidence")

    feedback = _extraction_audit_finalization_error_feedback(wrapper, error)

    assert "FINALIZATION_REJECTED" in feedback
    assert "DO NOT repeat page reads" in feedback
    assert "Repair attempt 1 of 3" in feedback
