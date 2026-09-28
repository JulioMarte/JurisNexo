from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

# Benchmark oracle deliberately lives outside the model prompt/provider path.
# These patterns are independently scored against the already-admitted text.
LEGAL_FACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "dates": re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"),
    "amounts": re.compile(r"(?i)(?:RD\$|US\$|DOP|USD)\s*\d[\d.,]*"),
    "articles": re.compile(r"(?i)\bart(?:í|i)culo\s+\d+(?:[.-]\d+)*\b"),
    "laws": re.compile(r"(?i)\bley\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"),
    "decrees": re.compile(r"(?i)\bdecreto(?:-ley)?\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"),
    "resolutions": re.compile(r"(?i)\bresoluci[oó]n\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"),
    "rnc": re.compile(r"(?i)\bRNC\b[\s:.#-]*\d{9}\b"),
    "cedulas": re.compile(r"(?i)\bc[eé]dula\b[\s:.#-]*\d{3}-?\d{7}-?\d\b"),
    "matriculas": re.compile(r"(?i)\bmatr[ií]cula\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"),
    "cadastral_references": re.compile(r"(?i)\b(?:parcela|distrito catastral|designaci[oó]n catastral)\b[^\n]{0,40}?\d[\d-]*"),
    "case_identifiers": re.compile(r"(?i)\b(?:TC|SCJ|expediente|sentencia)[\s:.-]*[A-Z0-9./-]{3,}\b"),
    "citations": re.compile(r"(?i)\bTC/\d{4}/\d{2}\b|\bSCJ-[A-Z0-9-]{4,}\b"),
}
FACT_FIELDS = tuple(LEGAL_FACT_PATTERNS)


def _canonical(value: str) -> str:
    return " ".join(value.split()).casefold()


def extract_reference_facts(text: str) -> dict[str, tuple[str, ...]]:
    return {
        field: tuple(match.group(0) for match in pattern.finditer(text))
        for field, pattern in LEGAL_FACT_PATTERNS.items()
    }


@dataclass(frozen=True, slots=True)
class FactScore:
    expected: int
    predicted: int
    matched: int

    @property
    def precision(self) -> float:
        if self.predicted == 0:
            return 1.0 if self.expected == 0 else 0.0
        return self.matched / self.predicted

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 0.0 if total == 0 else 2 * self.precision * self.recall / total


@dataclass(frozen=True, slots=True)
class LegalFactScore:
    fields: dict[str, FactScore]

    @property
    def expected(self) -> int:
        return sum(item.expected for item in self.fields.values())

    @property
    def predicted(self) -> int:
        return sum(item.predicted for item in self.fields.values())

    @property
    def matched(self) -> int:
        return sum(item.matched for item in self.fields.values())

    @property
    def hallucinated(self) -> int:
        return self.predicted - self.matched

    @property
    def missed(self) -> int:
        return self.expected - self.matched

    @property
    def precision(self) -> float:
        if self.predicted == 0:
            return 1.0 if self.expected == 0 else 0.0
        return self.matched / self.predicted

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 0.0 if total == 0 else 2 * self.precision * self.recall / total


def score_legal_facts(
    *,
    expected: Mapping[str, Sequence[str]],
    predicted: Mapping[str, Sequence[str]],
) -> LegalFactScore:
    scores: dict[str, FactScore] = {}
    for field in FACT_FIELDS:
        expected_counter = Counter(_canonical(value) for value in expected.get(field, ()))
        predicted_counter = Counter(_canonical(value) for value in predicted.get(field, ()))
        matched = sum((expected_counter & predicted_counter).values())
        scores[field] = FactScore(
            expected=sum(expected_counter.values()),
            predicted=sum(predicted_counter.values()),
            matched=matched,
        )
    return LegalFactScore(fields=scores)
