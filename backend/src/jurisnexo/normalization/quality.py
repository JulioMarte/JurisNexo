from __future__ import annotations

import re
from dataclasses import dataclass

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
