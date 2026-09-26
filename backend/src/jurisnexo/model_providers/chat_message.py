# ruff: noqa: E501, E701
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from jurisnexo.model_providers.contracts import JsonObject


def extract_chat_message_text(message: Mapping[str, object]) -> str:
    """Return conversational text, falling back to provider reasoning when needed."""
    text = _content_to_text(message.get("content"))
    if text.strip():
        return text
    for key in ("reasoning_content", "reasoning"):
        fallback = _content_to_text(message.get(key))
        if fallback.strip():
            return fallback
    raise TypeError("message has no textual content")


def extract_structured_object(message: Mapping[str, object]) -> JsonObject:
    """Return the final structured answer, never hidden/internal reasoning.

    `reasoning`, `reasoning_content`, and `reasoning_details` are evidence about
    how a model arrived at an answer; they are not the answer contract. This is
    deliberately stricter than `extract_chat_message_text` so a reasoning model
    cannot accidentally satisfy a JSON contract with chain-of-thought text.
    """
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return cast(JsonObject, parsed)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in cast(list[object], tool_calls):
            if not isinstance(tool_call, dict):
                continue
            function = cast(dict[str, object], tool_call).get("function")
            if not isinstance(function, dict):
                continue
            arguments = cast(dict[str, object], function).get("arguments")
            if isinstance(arguments, dict):
                return cast(JsonObject, arguments)
            if isinstance(arguments, str):
                loaded: object = json.loads(arguments)
                if not isinstance(loaded, dict):
                    raise TypeError("tool arguments are not a JSON object")
                return cast(JsonObject, loaded)

    text = _content_to_text(message.get("content"))
    if not text.strip():
        has_reasoning = any(
            bool(_content_to_text(message.get(key)).strip())
            for key in ("reasoning_content", "reasoning")
        ) or isinstance(message.get("reasoning_details"), list)
        if has_reasoning:
            raise TypeError("message has reasoning but no final structured content")
        raise TypeError("message has no final structured content")

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
    parts: list[str] = []
    for item in cast(list[object], content):
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        mapping = cast(dict[str, object], item)
        if mapping.get("type") not in (None, "text", "output_text"):
            continue
        piece = mapping.get("text")
        if isinstance(piece, str):
            parts.append(piece)
    return "".join(parts)


def validate_structured_object(value: JsonObject, schema: Mapping[str, object]) -> None:
    _validate_schema_value(value, schema, path="$")


def _validate_schema_value(value: object, schema: Mapping[str, object], *, path: str) -> None:
    declared = schema.get("type")
    allowed = tuple(item for item in cast(list[object], declared) if isinstance(item, str)) if isinstance(declared, list) else ((declared,) if isinstance(declared, str) else ())
    if allowed and not _matches_type(value, allowed):
        raise ValueError(f"structured response schema mismatch at {path}: expected {allowed}, got {type(value).__name__}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in cast(list[object], enum):
        raise ValueError(f"structured response schema mismatch at {path}: value {value!r} not in enum")
    if isinstance(value, dict):
        typed_value = cast(dict[str, object], value)
        properties_raw = schema.get("properties")
        properties = cast(dict[str, object], properties_raw) if isinstance(properties_raw, dict) else {}
        required_raw = schema.get("required")
        required = tuple(item for item in cast(list[object], required_raw) if isinstance(item, str)) if isinstance(required_raw, list) else ()
        missing = [key for key in required if key not in typed_value]
        if missing:
            raise ValueError(f"structured response schema mismatch at {path}: missing required keys {missing}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(typed_value) - set(properties))
            if extras:
                raise ValueError(f"structured response schema mismatch at {path}: unexpected keys {extras}")
        for key, child in typed_value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _validate_schema_value(child, cast(dict[str, object], child_schema), path=f"{path}.{key}")
        return
    if isinstance(value, list):
        typed_value_list = cast(list[object], value)
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(typed_value_list) > max_items:
            raise ValueError(f"structured response schema mismatch at {path}: {len(typed_value_list)} items exceeds maxItems={max_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(typed_value_list):
                _validate_schema_value(item, cast(dict[str, object], item_schema), path=f"{path}[{index}]")


def _matches_type(value: object, allowed: tuple[str, ...]) -> bool:
    for item in allowed:
        if item == "null" and value is None: return True
        if item == "object" and isinstance(value, dict): return True
        if item == "array" and isinstance(value, list): return True
        if item == "string" and isinstance(value, str): return True
        if item == "boolean" and isinstance(value, bool): return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool): return True
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool): return True
    return False
