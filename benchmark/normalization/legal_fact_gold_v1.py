from __future__ import annotations

import re
import unicodedata

# Independent benchmark oracle. This is deliberately benchmark-owned rather
# than imported from production normalization code. Changing these patterns
# changes the gold definition and therefore requires a benchmark version bump.
PATTERNS: dict[str, re.Pattern[str]] = {
    "dates": re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"),
    "money": re.compile(r"(?i)(?:RD\$|US\$|DOP|USD)\s*\d(?:[\d.,]*\d)?"),
    "articles": re.compile(r"(?i)\bart(?:í|i)culo\s+\d+(?:[.-]\d+)*\b"),
    "laws": re.compile(r"(?i)\bley\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"),
    "decrees": re.compile(
        r"(?i)\bdecreto(?:-ley)?\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "resolutions": re.compile(
        r"(?i)\bresoluci[oó]n\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "gaceta_official": re.compile(r"(?i)\bgaceta\s+oficial\b"),
    "rnc": re.compile(r"(?i)\bRNC\b[\s:.#-]*\d{9}\b"),
    "cedulas": re.compile(r"(?i)\bc[eé]dula\b[\s:.#-]*\d{3}-?\d{7}-?\d\b"),
    "matriculas": re.compile(
        r"(?i)\bmatr[ií]cula\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "cadastre": re.compile(
        r"(?i)\b(?:parcela|distrito catastral|designaci[oó]n catastral)\b"
        r"[^\n]{0,40}?\d[\d-]*"
    ),
    "case_ids": re.compile(
        r"(?i)\b(?:TC|SCJ|expediente|sentencia)[\s:.-]*[A-Z0-9./-]{3,}\b"
    ),
    "citations": re.compile(r"(?i)\bTC/\d{4}/\d{2}\b|\bSCJ-[A-Z0-9-]{4,}\b"),
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def extract_gold(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for field, pattern in PATTERNS.items():
        seen: set[str] = set()
        values: list[str] = []
        for match in pattern.finditer(text):
            value = " ".join(match.group(0).split())
            normalized = _normalize(value)
            if normalized in seen:
                continue
            seen.add(normalized)
            values.append(value)
        result[field] = values
    return result
