from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import cast

_REPLACEMENT = "\ufffd"
_CRITICAL_PATTERN = re.compile(
    r"(?i)\b(?:art(?:í|i)culo|ley|sentencia|expediente|núm(?:ero)?\.?|no\.?)\s*[-:#º°]?\s*[A-Z0-9./-]+"
)


@dataclass(frozen=True, slots=True)
class DeterministicQualityReport:
    character_count: int
    replacement_character_count: int
    empty_line_ratio: float
    suspicious_fragment_count: int
    legal_critical_span_count: int
    risk_flags: tuple[str, ...]

    @property
    def requires_review(self) -> bool:
        return bool(self.risk_flags)


def assess_text_quality(text: str) -> DeterministicQualityReport:
    lines = text.splitlines()
    character_count = len(text)
    replacement_count = text.count(_REPLACEMENT)
    empty_ratio = (
        sum(not line.strip() for line in lines) / len(lines)
        if lines
        else 1.0
    )
    fragments = sum(
        1 for line in lines
        if line.strip() and len(line.strip()) <= 2 and not line.strip().isdigit()
    )
    critical_spans = len(_CRITICAL_PATTERN.findall(text))

    flags: list[str] = []
    if not text.strip():
        flags.append("empty_text")
    if character_count and replacement_count / character_count > 0.001:
        flags.append("replacement_characters")
    if len(lines) >= 10 and empty_ratio > 0.65:
        flags.append("extreme_fragmentation")
    if len(lines) >= 10 and fragments / len(lines) > 0.20:
        flags.append("tiny_line_fragmentation")

    return DeterministicQualityReport(
        character_count=character_count,
        replacement_character_count=replacement_count,
        empty_line_ratio=empty_ratio,
        suspicious_fragment_count=fragments,
        legal_critical_span_count=critical_spans,
        risk_flags=tuple(flags),
    )


def _decode_json_pointer_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _resolve_json_pointer(document: object, ref: str) -> object:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported Docling reference: {ref}")
    current = document
    for raw_part in ref[2:].split("/"):
        part = _decode_json_pointer_part(raw_part)
        if isinstance(current, dict):
            mapping = cast(dict[str, object], current)
            if part not in mapping:
                raise ValueError(f"unresolvable Docling reference: {ref}")
            current = mapping[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise ValueError(
                    f"unresolvable Docling reference: {ref}"
                ) from exc
            sequence = cast(list[object], current)
            if index < 0 or index >= len(sequence):
                raise ValueError(f"unresolvable Docling reference: {ref}")
            current = sequence[index]
            continue
        raise ValueError(f"unresolvable Docling reference: {ref}")
    return current


def _table_cell_texts(node: dict[str, object]) -> tuple[str, ...]:
    data = node.get("data")
    if not isinstance(data, dict):
        return ()
    data_map = cast(dict[str, object], data)
    cells = data_map.get("table_cells")
    if not isinstance(cells, list):
        return ()

    sortable: list[tuple[int, int, str]] = []
    for raw_cell in cast(list[object], cells):
        if not isinstance(raw_cell, dict):
            continue
        cell = cast(dict[str, object], raw_cell)
        text = cell.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        row = cell.get("start_row_offset_idx")
        col = cell.get("start_col_offset_idx")
        sortable.append(
            (
                row if isinstance(row, int) else 0,
                col if isinstance(col, int) else 0,
                text,
            )
        )
    sortable.sort(key=lambda item: (item[0], item[1]))
    return tuple(text for _, _, text in sortable)


def extract_text_from_structural_json(payload: bytes) -> str:
    """Resolve Docling text in canonical body-tree reading order.

    Docling top-level content arrays are storage collections. The authoritative
    reading order is represented by the body tree and its JSON-pointer
    children. Walking every text key recursively can reorder or duplicate
    content, especially around tables and nested structures.
    """
    try:
        document: object = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("structural artifact is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("structural artifact root is not an object")

    root = cast(dict[str, object], document)
    body = root.get("body")
    parts: list[str] = []
    visited_refs: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, list):
            for child in cast(list[object], node):
                visit(child)
            return
        if not isinstance(node, dict):
            return

        mapping = cast(dict[str, object], node)
        ref = mapping.get("$ref")
        if isinstance(ref, str):
            if ref in visited_refs:
                return
            visited_refs.add(ref)
            visit(_resolve_json_pointer(root, ref))
            return

        text_value = mapping.get("text")
        if isinstance(text_value, str) and text_value.strip():
            parts.append(text_value)

        for cell_text in _table_cell_texts(mapping):
            parts.append(cell_text)

        children = mapping.get("children")
        if isinstance(children, list):
            visit(cast(list[object], children))

    if isinstance(body, dict):
        body_map = cast(dict[str, object], body)
        children = body_map.get("children")
        if isinstance(children, list):
            visit(cast(list[object], children))

    if parts:
        return "\n".join(parts)

    # Defensive fallback for older/minimal Docling-shaped artifacts that do not
    # expose a body tree. Restrict traversal to canonical content collections;
    # never recursively walk the entire exported JSON.
    texts = root.get("texts")
    if isinstance(texts, list):
        for item in cast(list[object], texts):
            if isinstance(item, dict):
                mapping = cast(dict[str, object], item)
                text_value = mapping.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    parts.append(text_value)

    tables = root.get("tables")
    if isinstance(tables, list):
        for item in cast(list[object], tables):
            if isinstance(item, dict):
                parts.extend(_table_cell_texts(cast(dict[str, object], item)))

    return "\n".join(parts)
