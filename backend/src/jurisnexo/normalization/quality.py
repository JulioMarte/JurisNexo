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


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def _decode_json_pointer_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _resolve_json_pointer(document: object, ref: str) -> object:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported Docling reference: {ref}")
    current = document
    for raw_part in ref[2:].split("/"):
        part = _decode_json_pointer_part(raw_part)
        mapping = _object_dict(current)
        if mapping is not None:
            if part not in mapping:
                raise ValueError(f"unresolvable Docling reference: {ref}")
            current = mapping[part]
            continue
        sequence = _object_list(current)
        if sequence is not None:
            try:
                index = int(part)
            except ValueError as exc:
                raise ValueError(
                    f"unresolvable Docling reference: {ref}"
                ) from exc
            if index < 0 or index >= len(sequence):
                raise ValueError(f"unresolvable Docling reference: {ref}")
            current = sequence[index]
            continue
        raise ValueError(f"unresolvable Docling reference: {ref}")
    return current


def _table_cell_texts(node: dict[str, object]) -> tuple[str, ...]:
    data = node.get("data")
    data_map = _object_dict(data)
    if data_map is None:
        return ()
    cells = data_map.get("table_cells")
    cell_items = _object_list(cells)
    if cell_items is None:
        return ()

    sortable: list[tuple[int, int, str]] = []
    for raw_cell in cell_items:
        cell = _object_dict(raw_cell)
        if cell is None:
            continue
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
    root = _object_dict(document)
    if root is None:
        raise ValueError("structural artifact root is not an object")
    body = root.get("body")
    parts: list[str] = []
    visited_refs: set[str] = set()

    def visit(node: object) -> None:
        sequence = _object_list(node)
        if sequence is not None:
            for child in sequence:
                visit(child)
            return
        mapping = _object_dict(node)
        if mapping is None:
            return
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

        children = _object_list(mapping.get("children"))
        if children is not None:
            visit(children)

    body_map = _object_dict(body)
    if body_map is not None:
        children = _object_list(body_map.get("children"))
        if children is not None:
            visit(children)

    if parts:
        return "\n".join(parts)

    # Defensive fallback for older/minimal Docling-shaped artifacts that do not
    # expose a body tree. Restrict traversal to canonical content collections;
    # never recursively walk the entire exported JSON.
    texts = _object_list(root.get("texts"))
    if texts is not None:
        for item in texts:
            mapping = _object_dict(item)
            if mapping is None:
                continue
            text_value = mapping.get("text")
            if isinstance(text_value, str) and text_value.strip():
                parts.append(text_value)

    tables = _object_list(root.get("tables"))
    if tables is not None:
        for item in tables:
            mapping = _object_dict(item)
            if mapping is not None:
                parts.extend(_table_cell_texts(mapping))

    return "\n".join(parts)
