from __future__ import annotations

import pytest

from jurisnexo.model_providers.chat_message import extract_chat_message_text


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
