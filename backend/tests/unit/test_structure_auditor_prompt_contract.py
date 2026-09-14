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
    assert "Do not replay every prior call" in instructions or "Do not re-read every unchanged" in instructions
    assert "not a legal extraction agent" in instructions
    assert "minimum independent evidence" in instructions
    assert "Tool-call volume is not confidence" in instructions
    assert "carried_forward" in instructions
    assert "runtime marks that finding_id as eligible" in instructions
    assert "small independent regression sample" in instructions
    assert "APPROVED unlocks" in instructions
