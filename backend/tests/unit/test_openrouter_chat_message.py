from __future__ import annotations

import pytest

from jurisnexo.model_providers.chat_message import (
    extract_chat_message_text,
    extract_structured_object,
)


def test_extracts_plain_string_content() -> None:
    assert extract_chat_message_text({"content": "{}"}) == "{}"


def test_extracts_content_part_list() -> None:
    message = {
        "content": [
            {"type": "text", "text": '{"matches":'},
            {"type": "text", "text": " true}"},
        ]
    }
    assert extract_chat_message_text(message) == '{"matches": true}'


def test_extracts_dict_content() -> None:
    assert extract_chat_message_text({"content": {"text": "ok"}}) == "ok"


def test_ignores_non_text_parts() -> None:
    message = {
        "content": [
            {"type": "reasoning", "text": "hidden"},
            {"type": "text", "text": "visible"},
        ]
    }
    assert extract_chat_message_text(message) == "visible"


def test_falls_back_to_reasoning_content_when_content_empty() -> None:
    message = {"content": None, "reasoning_content": '{"escalate": false}'}
    assert extract_chat_message_text(message) == '{"escalate": false}'


def test_raises_when_no_textual_content_exists() -> None:
    with pytest.raises(TypeError):
        extract_chat_message_text({"content": None})


def test_structured_object_uses_preparsed_value() -> None:
    message = {"parsed": {"matches": True}, "content": "ignored"}
    assert extract_structured_object(message) == {"matches": True}


def test_structured_object_strips_markdown_fence() -> None:
    message = {"content": '```json\n{"matches": false, "corrected_text": null}\n```'}
    assert extract_structured_object(message) == {
        "matches": False,
        "corrected_text": None,
    }


def test_structured_object_recovers_object_from_prose() -> None:
    message = {"content": 'Result follows.\n{"escalate": false, "risk": "low"}'}
    assert extract_structured_object(message) == {
        "escalate": False,
        "risk": "low",
    }


def test_structured_object_rejects_non_object_json() -> None:
    with pytest.raises(TypeError):
        extract_structured_object({"content": "[1, 2, 3]"})


def test_structured_object_rejects_non_json_text() -> None:
    with pytest.raises(ValueError):
        extract_structured_object({"content": "no json here"})


def test_structured_object_uses_tool_call_arguments() -> None:
    message = {
        "content": "",
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": "jurisnexo_visual_verification",
                    "arguments": '{"matches": true, "corrected_text": null, "material_differences": []}',
                },
            }
        ],
    }
    assert extract_structured_object(message) == {
        "matches": True,
        "corrected_text": None,
        "material_differences": [],
    }
