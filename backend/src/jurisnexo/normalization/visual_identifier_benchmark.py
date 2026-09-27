from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

SCJ_IDENTIFIER_PATTERN = re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VisualIdentifierCase:
    object_key: str
    page_index: int
    expected_identifier: str
    gold_source: str


def extract_scj_identifier(text: str) -> str | None:
    match = SCJ_IDENTIFIER_PATTERN.search(text or "")
    return match.group(0).upper() if match is not None else None


def select_visual_identifier_cases(
    cases: list[VisualIdentifierCase],
    *,
    sample_size: int,
    selection: str,
    seed: int,
) -> list[VisualIdentifierCase]:
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    if sample_size > len(cases):
        raise ValueError(
            f"requested {sample_size} cases but only {len(cases)} available"
        )
    if selection == "deterministic":
        return cases[:sample_size]
    if selection == "random":
        return random.Random(seed).sample(cases, sample_size)
    raise ValueError("selection must be deterministic or random")


def load_visual_identifier_manifest(path: str | Path) -> list[VisualIdentifierCase]:
    loaded: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    rows_raw: Any
    if isinstance(loaded, dict):
        loaded_dict = cast(dict[str, Any], loaded)
        rows_raw = loaded_dict.get("cases", loaded_dict)
    else:
        rows_raw = loaded
    if not isinstance(rows_raw, list):
        raise ValueError(
            "visual identifier manifest must contain a list of cases"
        )
    rows = cast(list[Any], rows_raw)
    cases: list[VisualIdentifierCase] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError("each visual case must be an object")
        row = cast(dict[str, Any], raw_row)
        cases.append(
            VisualIdentifierCase(
                object_key=str(row["object_key"]),
                page_index=int(row["page_index"]),
                expected_identifier=str(
                    row["expected_identifier"]
                ).upper(),
                gold_source=str(
                    row.get("gold_source") or "curated"
                ),
            )
        )
    return cases
