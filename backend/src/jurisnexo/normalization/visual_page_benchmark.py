from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class VisualPageCase:
    object_key: str
    page_index: int
    gold_source: str


def select_visual_page_cases(
    cases: list[VisualPageCase],
    *,
    sample_size: int,
    selection: str,
    seed: int,
) -> list[VisualPageCase]:
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


def load_visual_page_manifest(path: str | Path) -> list[VisualPageCase]:
    loaded: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    rows_raw: Any
    if isinstance(loaded, dict):
        loaded_dict = cast(dict[str, Any], loaded)
        rows_raw = loaded_dict.get("cases", loaded_dict)
    else:
        rows_raw = loaded
    if not isinstance(rows_raw, list):
        raise ValueError("visual page manifest must contain a list of cases")
    rows = cast(list[Any], rows_raw)
    cases: list[VisualPageCase] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise ValueError("each visual page case must be an object")
        row = cast(dict[str, Any], raw_row)
        cases.append(
            VisualPageCase(
                object_key=str(row["object_key"]),
                page_index=int(row["page_index"]),
                gold_source=str(row.get("gold_source") or "curated"),
            )
        )
    return cases
