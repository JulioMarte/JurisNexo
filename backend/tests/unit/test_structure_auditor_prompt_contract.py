from __future__ import annotations

import pytest

from jurisnexo.ingestion.sdk_structure_auditor import build_structure_auditor

pytestmark = pytest.mark.unit


def test_structure_auditor_instructions_require_independent_source_review() -> None:
    auditor = build_structure_auditor(model="gpt-5.6-luna")
    instructions = auditor.instructions

    assert isinstance(instructions, str)
    assert "independently verify" in instructions
    assert "must not approve" in instructions
    assert "Use workspace tools to inspect source evidence yourself" in instructions
    assert "Every supported or contradicted material check must cite typed evidence" in instructions
    assert "Unknown is preferable to unsupported certainty" in instructions
