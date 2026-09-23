from __future__ import annotations

from collections.abc import Mapping
from typing import cast


def extract_chat_message_text(message: Mapping[str, object]) -> str:
    """Return the textual payload of a chat-completions message.

    OpenAI-compatible providers return ``content`` either as a plain string or
    as a list of content parts, and reasoning models may leave ``content`` empty
    while placing the payload under a reasoning field. The structured-output
    callers only care about the textual payload, so normalize all of these
    shapes here instead of failing on a provider-specific representation.
    """

    text = _content_to_text(message.get("content"))
    if text:
        return text
    for key in ("reasoning_content", "reasoning"):
        fallback = _content_to_text(message.get(key))
        if fallback:
            return fallback
    raise TypeError("message has no textual content")


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        mapping = cast(dict[str, object], content)
        piece = mapping.get("text")
        return piece if isinstance(piece, str) else ""
    if not isinstance(content, list):
        return ""
    items = cast(list[object], content)
    parts: list[str] = []
    for item in items:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        mapping = cast(dict[str, object], item)
        part_type = mapping.get("type")
        if part_type not in (None, "text", "output_text"):
            continue
        piece = mapping.get("text")
        if isinstance(piece, str):
            parts.append(piece)
    return "".join(parts)
