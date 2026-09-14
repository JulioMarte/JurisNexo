from __future__ import annotations

import json
from pathlib import Path

import pytest

from jurisnexo.ingestion.structure_trace import StructureToolTraceRecorder, render_tool_trace

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def test_trace_records_digest_excerpt_and_arguments() -> None:
    recorder = StructureToolTraceRecorder(excerpt_chars=200)

    recorder.record_success(
        tool_name="get_page",
        arguments={"page_number": 7},
        result="SENTENCIA" * 100,
    )

    event = recorder.events[0]
    assert event.sequence == 1
    assert event.stage == "structure_agent"
    assert event.occurred_at.tzinfo is not None
    assert event.tool_name == "get_page"
    assert event.arguments == {"page_number": 7}
    assert event.status == "success"
    assert event.result_char_count == len("SENTENCIA" * 100)
    assert len(event.result_sha256 or "") == 64
    assert len(event.result_excerpt) == 200


def test_trace_records_errors_without_swallowing_identity() -> None:
    recorder = StructureToolTraceRecorder()

    recorder.record_error(
        tool_name="get_printed_page",
        arguments={"printed_page_number": 999},
        error=ValueError("missing page"),
    )

    event = recorder.events[0]
    assert event.status == "error"
    assert event.error_type == "ValueError"
    assert event.error_message == "missing page"


def test_trace_journal_is_appended_immediately(tmp_path: Path) -> None:
    journal = tmp_path / "trace.jsonl"
    recorder = StructureToolTraceRecorder(
        stage="structure_auditor",
        journal_path=journal,
    )

    recorder.record_success(
        tool_name="get_page",
        arguments={"page_number": 1},
        result="first result",
    )
    first_lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(first_lines) == 1
    assert json.loads(first_lines[0])["stage"] == "structure_auditor"

    recorder.record_error(
        tool_name="get_page",
        arguments={"page_number": 999},
        error=ValueError("bad page"),
    )
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["status"] == "error"


def test_render_tool_trace_is_bounded_and_preserves_omission_marker() -> None:
    recorder = StructureToolTraceRecorder(excerpt_chars=200)
    for page in range(1, 30):
        recorder.record_success(
            tool_name="get_page",
            arguments={"page_number": page},
            result="x" * 500,
        )

    rendered = render_tool_trace(recorder.events, max_chars=2_000)

    assert "trace truncated" in rendered
    assert '"tool_name":"get_page"' in rendered.replace(" ", "")