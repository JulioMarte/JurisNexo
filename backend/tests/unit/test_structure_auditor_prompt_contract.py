from __future__ import annotations

import pytest

from jurisnexo.ingestion.sdk_structure_auditor import build_structure_auditor

pytestmark = pytest.mark.unit


def test_structure_auditor_instructions_require_adversarial_source_review() -> None:
    auditor = build_structure_auditor(model="gpt-5.6-luna")
    instructions = auditor.instructions

    assert isinstance(instructions, str)
    assert "try to falsify" in instructions
    assert "Use the same read-only workspace tools" in instructions
    assert "adversarial sampling" in instructions
    assert "NOT an extraction agent" in instructions
    assert "do not verify every work unit" in instructions
    assert (
        "Every supported or contradicted material check must cite typed evidence"
        in instructions
    )
    assert "APPROVED does not assert" in instructions
