from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from jurisnexo.model_providers.contracts import JsonObject


def extract_chat_message_text(message: Mapping[str, object]) -> str:
    """Return the textual payload of a chat-completions message.

    OpenAI-compatible providers return ``content`` either as a plain string or
    as a list of content parts, and reasoning models may leave ``content`` empty
    while placing the payload under a reasoning field. The structured-output
    callers only care about the textual payload, so normalize all of these
    shapes here instead of failing on a provider-specific representation.
    """

    text = _content_to_text(message.get("content"))
    if text.strip():
        return text
    for key in ("reasoning_content", "reasoning"):
        fallback = _content_to_text(message.get(key))
        if fallback.strip():
            return fallback
    raise TypeError("message has no textual content")


def extract_structured_object(message: Mapping[str, object]) -> JsonObject:
    """Return the JSON object of a structured-output message.

    Providers occasionally pre-parse the object into ``message.parsed`` and
    otherwise wrap the JSON in prose or Markdown code fences. Normalize those
    shapes and raise a diagnosable error (with a short preview) when the payload
    is not a JSON object.
    """

    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return cast(JsonObject, parsed)

    text = extract_chat_message_text(message)
    candidate = _json_candidate(text)
    try:
        loaded: object = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"structured response is not valid JSON: preview={text[:300]!r}"
        ) from exc
    if not isinstance(loaded, dict):
        raise TypeError(
            "structured response is not a JSON object: "
            f"preview={text[:300]!r}"
        )
    return cast(JsonObject, loaded)


def _json_candidate(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline != -1:
            candidate = candidate[first_newline + 1 :]
        stripped = candidate.rstrip()
        if stripped.endswith("```"):
            candidate = stripped[:-3]
    candidate = candidate.strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
    return candidate


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
