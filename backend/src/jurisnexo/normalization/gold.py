from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\S+")
_CONTENT_TOKEN_RE = re.compile(r"\w+(?:[./-]\w+)*", re.UNICODE)
_CRITICAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "date": re.compile(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
    ),
    "money": re.compile(
        r"(?i)(?:RD\$|US\$|DOP|USD)\s*\d[\d.,]*"
    ),
    "article": re.compile(
        r"(?i)\bart(?:í|i)culo\s+\d+(?:[.-]\d+)*\b"
    ),
    "law": re.compile(
        r"(?i)\bley\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "decree": re.compile(
        r"(?i)\bdecreto(?:-ley)?\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "resolution": re.compile(
        r"(?i)\bresoluci[oó]n\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "gaceta": re.compile(
        r"(?i)\bgaceta\s+oficial\b"
    ),
    "rnc": re.compile(
        r"(?i)\bRNC\b[\s:.#-]*\d{9}\b"
    ),
    "cedula": re.compile(
        r"(?i)\bc[eé]dula\b[\s:.#-]*\d{3}-?\d{7}-?\d\b"
    ),
    "matricula": re.compile(
        r"(?i)\bmatr[ií]cula\s+(?:núm(?:ero)?\.?\s*)?\d+[\d-]*\b"
    ),
    "cadastre": re.compile(
        r"(?i)\b(?:parcela|distrito catastral|designaci[oó]n catastral)\b"
        r"[^\n]{0,40}?\d[\d-]*"
    ),
    "case_id": re.compile(
        r"(?i)\b(?:TC|SCJ|expediente|sentencia)[\s:.-]*[A-Z0-9./-]{3,}\b"
    ),
    "citation": re.compile(
        r"(?i)\bTC/\d{4}/\d{2}\b|\bSCJ-[A-Z0-9-]{4,}\b"
    ),
}


@dataclass(frozen=True, slots=True)
class ReferenceTextHealth:
    character_count: int
    replacement_character_count: int
    suspicious_character_count: int
    suspicious_character_rate: float
    risk_flags: tuple[str, ...]

    @property
    def is_reliable(self) -> bool:
        return not self.risk_flags


def assess_reference_text_health(
    text: str,
    *,
    suspicious_characters: frozenset[str] = frozenset(),
    minimum_suspicious_count: int = 3,
    maximum_suspicious_rate: float = 0.002,
) -> ReferenceTextHealth:
    """Detect when an extracted reference is unsafe to treat as ground truth.

    The caller owns any source/language-specific suspicious-character set.
    The generic scorer only enforces explicit, measurable thresholds and always
    treats Unicode replacement characters as reference corruption.
    """

    if minimum_suspicious_count < 1:
        raise ValueError("minimum_suspicious_count must be positive")
    if not 0.0 <= maximum_suspicious_rate <= 1.0:
        raise ValueError("maximum_suspicious_rate must stay within [0, 1]")

    character_count = len(text)
    replacement_count = text.count("\ufffd")
    suspicious_count = sum(
        character in suspicious_characters for character in text
    )
    suspicious_rate = (
        suspicious_count / character_count if character_count else 0.0
    )
    flags: list[str] = []
    if not text.strip():
        flags.append("empty_reference")
    if replacement_count:
        flags.append("replacement_characters")
    if (
        suspicious_count >= minimum_suspicious_count
        and suspicious_rate > maximum_suspicious_rate
    ):
        flags.append("probable_mojibake")
    return ReferenceTextHealth(
        character_count=character_count,
        replacement_character_count=replacement_count,
        suspicious_character_count=suspicious_count,
        suspicious_character_rate=suspicious_rate,
        risk_flags=tuple(flags),
    )


@dataclass(frozen=True, slots=True)
class CriticalCategoryScore:
    expected: int
    matched: int

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected


@dataclass(frozen=True, slots=True)
class TextFidelityScore:
    character_error_rate: float
    word_error_rate: float
    token_content_recall: float
    token_content_precision: float
    token_content_f1: float
    token_order_preservation: float
    missing_span_count: int
    critical: dict[str, CriticalCategoryScore]

    @property
    def legal_critical_recall(self) -> float:
        expected = sum(item.expected for item in self.critical.values())
        matched = sum(item.matched for item in self.critical.values())
        return 1.0 if expected == 0 else matched / expected


@dataclass(frozen=True, slots=True)
class DocumentFidelityScore:
    page_count: int
    worst_page_word_error_rate: float
    worst_page_character_error_rate: float
    pages_with_missing_critical: int
    aggregate_legal_critical_recall: float

    @property
    def has_critical_loss(self) -> bool:
        return self.pages_with_missing_critical > 0


def score_document_fidelity(
    pages: tuple[TextFidelityScore, ...],
) -> DocumentFidelityScore:
    """Aggregate page scores into document-level worst-case evidence.

    Legal review cares about the worst page and about any critical loss, not
    only the corpus mean. A document with a perfect average but a missing
    dispositive identifier is unusable, so these tails are tracked explicitly.
    """

    if not pages:
        raise ValueError("document fidelity requires at least one page")
    expected_critical = sum(
        item.expected for page in pages for item in page.critical.values()
    )
    matched_critical = sum(
        item.matched for page in pages for item in page.critical.values()
    )
    return DocumentFidelityScore(
        page_count=len(pages),
        worst_page_word_error_rate=max(
            page.word_error_rate for page in pages
        ),
        worst_page_character_error_rate=max(
            page.character_error_rate for page in pages
        ),
        pages_with_missing_critical=sum(
            any(
                item.expected > item.matched
                for item in page.critical.values()
            )
            for page in pages
        ),
        aggregate_legal_critical_recall=(
            1.0
            if expected_critical == 0
            else matched_critical / expected_critical
        ),
    )


def _levenshtein_distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_value in enumerate(left, start=1):
        current = [row]
        for col, right_value in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[col] + 1,
                    previous[col - 1] + (left_value != right_value),
                )
            )
        previous = current
    return previous[-1]


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


def _longest_common_subsequence_length(
    left: list[str],
    right: list[str],
) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    for left_value in left:
        current = [0]
        for index, right_value in enumerate(right, start=1):
            if left_value == right_value:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _content_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in _CONTENT_TOKEN_RE.findall(text)
    )


def _content_overlap(
    expected_text: str,
    candidate_text: str,
) -> tuple[float, float, float]:
    expected = Counter(_content_tokens(expected_text))
    candidate = Counter(_content_tokens(candidate_text))
    matched = sum((expected & candidate).values())
    expected_count = sum(expected.values())
    candidate_count = sum(candidate.values())
    recall = 1.0 if expected_count == 0 else matched / expected_count
    precision = 1.0 if candidate_count == 0 and expected_count == 0 else (
        0.0 if candidate_count == 0 else matched / candidate_count
    )
    f1 = (
        0.0
        if recall + precision == 0.0
        else 2 * recall * precision / (recall + precision)
    )
    return recall, precision, f1


def _critical_values(
    text: str,
    pattern: re.Pattern[str],
) -> tuple[str, ...]:
    return tuple(
        _normalize_space(match.group(0)).casefold()
        for match in pattern.finditer(text)
    )


def score_text_fidelity(
    *,
    expected_text: str,
    candidate_text: str,
    required_spans: tuple[str, ...] = (),
) -> TextFidelityScore:
    expected_chars = list(expected_text)
    candidate_chars = list(candidate_text)
    char_distance = _levenshtein_distance(expected_chars, candidate_chars)
    character_error_rate = (
        0.0
        if not expected_chars and not candidate_chars
        else char_distance / max(1, len(expected_chars))
    )

    expected_words = _TOKEN_RE.findall(expected_text)
    candidate_words = _TOKEN_RE.findall(candidate_text)
    word_distance = _levenshtein_distance(expected_words, candidate_words)
    word_error_rate = (
        0.0
        if not expected_words and not candidate_words
        else word_distance / max(1, len(expected_words))
    )

    (
        token_content_recall,
        token_content_precision,
        token_content_f1,
    ) = _content_overlap(expected_text, candidate_text)

    expected_content_tokens = list(_content_tokens(expected_text))
    candidate_content_tokens = list(_content_tokens(candidate_text))
    token_order_preservation = (
        1.0
        if not expected_content_tokens
        else _longest_common_subsequence_length(
            expected_content_tokens,
            candidate_content_tokens,
        )
        / len(expected_content_tokens)
    )

    candidate_folded = candidate_text.casefold()
    missing_span_count = sum(
        span.casefold() not in candidate_folded
        for span in required_spans
    )

    critical: dict[str, CriticalCategoryScore] = {}
    for category, pattern in _CRITICAL_PATTERNS.items():
        expected_values = _critical_values(expected_text, pattern)
        candidate_values = list(_critical_values(candidate_text, pattern))
        matched = 0
        for value in expected_values:
            if value in candidate_values:
                candidate_values.remove(value)
                matched += 1
        critical[category] = CriticalCategoryScore(
            expected=len(expected_values),
            matched=matched,
        )

    return TextFidelityScore(
        character_error_rate=character_error_rate,
        word_error_rate=word_error_rate,
        token_content_recall=token_content_recall,
        token_content_precision=token_content_precision,
        token_content_f1=token_content_f1,
        token_order_preservation=token_order_preservation,
        missing_span_count=missing_span_count,
        critical=critical,
    )
