from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

SCJ_IDENTIFIER_PATTERN = re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE)
VERIFICATION_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    SCJ_IDENTIFIER_PATTERN,
    re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){2,}\b", re.IGNORECASE),
    re.compile(r"\b\d{4,}\b"),
)


@dataclass(frozen=True, slots=True)
class VisualIdentifierCase:
    object_key: str
    page_index: int
    expected_identifier: str
    gold_source: str


def extract_scj_identifier(text: str) -> str | None:
    match = SCJ_IDENTIFIER_PATTERN.search(text or "")
    return match.group(0).upper() if match is not None else None




def select_verification_target(text: str) -> tuple[str, str] | None:
    """Return a unique visible token and a guaranteed-absent corruption.

    A benchmark corruption is valid only when the source token occurs exactly
    once on the page and the one-character mutant does not occur anywhere in
    the reference text. This avoids counting a different, genuinely visible
    year or identifier as a model error.
    """

    source = text or ""
    folded = source.casefold()
    for pattern in VERIFICATION_TOKEN_PATTERNS:
        for match in pattern.finditer(source):
            token = match.group(0)
            if folded.count(token.casefold()) != 1:
                continue
            characters = list(token)
            digit_positions = [
                index
                for index in range(len(characters) - 1, -1, -1)
                if characters[index].isdigit()
            ]
            for index in digit_positions:
                original_digit = characters[index]
                for replacement in "9876543210":
                    if replacement == original_digit:
                        continue
                    mutated = characters.copy()
                    mutated[index] = replacement
                    candidate = "".join(mutated)
                    if candidate.casefold() not in folded:
                        return token, candidate
    return None


def visible_token_is_exact(
    *,
    expected_visible_token: str,
    observed_visible_token: object,
) -> bool:
    return (
        isinstance(observed_visible_token, str)
        and observed_visible_token == expected_visible_token
    )


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
