"""Deterministic analysis of the SCJ Principales Ling literal OCR evidence.

This module is pure: it consumes already-persisted Pass 1 / Pass 2 records and
returns routing evidence about divergence, output quality, legal-critical span
disagreements and runtime economics. It never calls a model and never treats a
transcription as ground truth; every result is a signal for later independent
adjudication, not a semantic correctness claim.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from jurisnexo.normalization.benchmark_suite import percentile

CHANGE_EXACT = "exact"
CHANGE_WHITESPACE = "whitespace"
CHANGE_CASE = "case"
CHANGE_ACCENT = "accent"
CHANGE_PUNCTUATION = "punctuation"
CHANGE_DIGITS = "digits"
CHANGE_SUBSTANTIVE = "substantive"
CHANGE_CLASSES: tuple[str, ...] = (
    CHANGE_EXACT,
    CHANGE_WHITESPACE,
    CHANGE_CASE,
    CHANGE_ACCENT,
    CHANGE_PUNCTUATION,
    CHANGE_DIGITS,
    CHANGE_SUBSTANTIVE,
)

IDENTIFIER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){1,}\b")
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
MONEY_PATTERN = re.compile(
    r"(?:RD\$|DOP|\$)\s?\d[\d.,]*|\d[\d.,]*\s*(?:pesos|d[oó]lares)",
    re.IGNORECASE,
)
REFERENCE_PATTERN = re.compile(
    r"\b(?:art[íi]culos?|ley|resoluci[óo]n|decreto)\s+(?:n[oº°]?\s*)?\d+",
    re.IGNORECASE,
)
WRAPPER_PATTERN = re.compile(r"---\s*(?:BEGIN|END)\s+OCR\s*---", re.IGNORECASE)
FENCE_PATTERN = re.compile(r"```")
ILEGIBLE_PATTERN = re.compile(r"\[\s*ilegible\s*\]", re.IGNORECASE)
NON_TRANSCRIPTION_PATTERN = re.compile(
    r"^\s*(?:i cannot|i can'?t|i'?m sorry|as an ai|lo siento|"
    r"como (?:una )?ia|no puedo proporcionar|the transcription|here is the transcription)",
    re.IGNORECASE,
)
REPEATED_CHARACTER_PATTERN = re.compile(r"([^\W_])\1{29,}", re.UNICODE)

ANOMALY_EMPTY = "empty"
ANOMALY_WRAPPER = "wrapper_only"
ANOMALY_FENCE = "markdown_fence"
ANOMALY_ILEGIBLE = "ilegible_marker"
ANOMALY_NON_TRANSCRIPTION = "non_transcription"
ANOMALY_REPETITION = "repetition_loop"
ANOMALY_REPEATED_CHARACTER = "repeated_character"
ANOMALIES: tuple[str, ...] = (
    ANOMALY_EMPTY,
    ANOMALY_WRAPPER,
    ANOMALY_FENCE,
    ANOMALY_ILEGIBLE,
    ANOMALY_NON_TRANSCRIPTION,
    ANOMALY_REPETITION,
    ANOMALY_REPEATED_CHARACTER,
)

LEGAL_CATEGORIES: tuple[str, ...] = ("identifier", "year", "date", "money", "reference")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def classify_change(first: str, second: str) -> str:
    """Classify the most specific normalization that makes both passes equal."""

    if first == second:
        return CHANGE_EXACT
    if normalize_whitespace(first) == normalize_whitespace(second):
        return CHANGE_WHITESPACE
    if normalize_whitespace(first).casefold() == normalize_whitespace(second).casefold():
        return CHANGE_CASE
    left, right = strip_accents(normalize_whitespace(first)), strip_accents(
        normalize_whitespace(second)
    )
    if left.casefold() == right.casefold():
        return CHANGE_ACCENT
    left_punct, right_punct = _strip_non_word(left), _strip_non_word(right)
    if left_punct.casefold() == right_punct.casefold():
        return CHANGE_PUNCTUATION
    if _strip_digits(left_punct).casefold() == _strip_digits(right_punct).casefold():
        return CHANGE_DIGITS
    return CHANGE_SUBSTANTIVE


def _strip_non_word(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text)


def _strip_digits(text: str) -> str:
    return re.sub(r"\d", "", text)


def substantive_similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, first, second).ratio()


def legal_spans(text: str) -> dict[str, frozenset[str]]:
    return {
        "identifier": frozenset(IDENTIFIER_PATTERN.findall(text)),
        "year": frozenset(YEAR_PATTERN.findall(text)),
        "date": frozenset(DATE_PATTERN.findall(text)),
        "money": frozenset(
            normalize_whitespace(m.group(0)) for m in MONEY_PATTERN.finditer(text)
        ),
        "reference": frozenset(
            normalize_whitespace(m.group(0)).casefold()
            for m in REFERENCE_PATTERN.finditer(text)
        ),
    }


def legal_span_disagreements(first: str, second: str) -> dict[str, dict[str, list[str]]]:
    first_spans, second_spans = legal_spans(first), legal_spans(second)
    disagreements: dict[str, dict[str, list[str]]] = {}
    for category in LEGAL_CATEGORIES:
        missing_from_second = first_spans[category] - second_spans[category]
        missing_from_first = second_spans[category] - first_spans[category]
        if missing_from_second or missing_from_first:
            disagreements[category] = {
                "first_only": sorted(missing_from_second),
                "second_only": sorted(missing_from_first),
            }
    return disagreements


def has_repetition_loop(text: str, *, min_repeats: int = 6) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    run = 1
    for previous, current in zip(lines, lines[1:], strict=False):
        if current == previous:
            run += 1
            if run >= min_repeats:
                return True
        else:
            run = 1
    return False


def detect_anomalies(text: str) -> frozenset[str]:
    found: set[str] = set()
    if not normalize_whitespace(text):
        found.add(ANOMALY_EMPTY)
    if WRAPPER_PATTERN.search(text):
        found.add(ANOMALY_WRAPPER)
    if FENCE_PATTERN.search(text):
        found.add(ANOMALY_FENCE)
    if ILEGIBLE_PATTERN.search(text):
        found.add(ANOMALY_ILEGIBLE)
    if NON_TRANSCRIPTION_PATTERN.search(text):
        found.add(ANOMALY_NON_TRANSCRIPTION)
    if has_repetition_loop(text):
        found.add(ANOMALY_REPETITION)
    if REPEATED_CHARACTER_PATTERN.search(text):
        found.add(ANOMALY_REPEATED_CHARACTER)
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class PassEvidence:
    transcription: str
    completion_tokens: int
    cost_usd: float
    latency_seconds: float
    returned_model: str
    returned_provider: str
    render_pixel_sha256: str | None


@dataclass(frozen=True, slots=True)
class PageEvidence:
    document_id: str
    page_index: int
    source_classification: str
    first: PassEvidence
    second: PassEvidence | None


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pass_evidence_from_mapping(mapping: Mapping[str, Any]) -> PassEvidence:
    render_pixel_sha256 = mapping.get("render_pixel_sha256")
    return PassEvidence(
        transcription=str(mapping.get("transcription") or ""),
        completion_tokens=_as_int(mapping.get("tokens_completion")),
        cost_usd=_as_float(mapping.get("total_cost_usd")),
        latency_seconds=_as_float(mapping.get("latency_seconds_client")),
        returned_model=str(mapping.get("returned_model") or ""),
        returned_provider=str(mapping.get("returned_provider") or ""),
        render_pixel_sha256=(
            str(render_pixel_sha256)
            if isinstance(render_pixel_sha256, str) and render_pixel_sha256
            else None
        ),
    )


def analyze_evidence(
    pages: Sequence[PageEvidence],
    *,
    expected_model: str,
    expected_provider: str,
    truncation_token_threshold: int = 16000,
    largest_rewrite_limit: int = 10,
    anomaly_example_limit: int = 5,
) -> dict[str, Any]:
    taxonomy: Counter[str] = Counter()
    anomalies: dict[str, Counter[str]] = {
        "pass1": Counter(),
        "pass2": Counter(),
    }
    anomaly_examples: dict[str, list[str]] = {}
    legal_disagreements: list[dict[str, Any]] = []
    rewrite_candidates: list[tuple[float, int, str, int]] = []
    similarities: list[float] = []
    classifications: Counter[str] = Counter()
    documents: dict[str, dict[str, Any]] = {}
    runtime: dict[str, Any] = {
        "returned_model_mismatch": 0,
        "returned_provider_mismatch": 0,
        "truncation_suspects": 0,
        "render_pixel_verified": 0,
        "render_legacy_unverified": 0,
        "completion_tokens_total": 0,
        "cost_total_usd": 0.0,
        "cost_pass1_usd": 0.0,
        "cost_pass2_usd": 0.0,
        "latency_seconds_total": 0.0,
    }
    missing_second_pass = 0

    for page in pages:
        classifications[page.source_classification] += 1
        doc = documents.setdefault(
            page.document_id,
            {
                "document_id": page.document_id,
                "pages": 0,
                "changed": 0,
                "substantive": 0,
                "legal_disagreements": 0,
                "anomalies": 0,
                "cost_usd": 0.0,
            },
        )
        doc["pages"] += 1
        _accumulate_pass(
            runtime,
            doc,
            page.first,
            expected_model,
            expected_provider,
            truncation_token_threshold,
            1,
        )
        example_id = f"{page.document_id}/{page.page_index}"
        for label in detect_anomalies(page.first.transcription):
            anomalies["pass1"][label] += 1
            doc["anomalies"] += 1
            anomaly_examples.setdefault(f"pass1:{label}", [])
            if len(anomaly_examples[f"pass1:{label}"]) < anomaly_example_limit:
                anomaly_examples[f"pass1:{label}"].append(example_id)

        if page.second is None:
            missing_second_pass += 1
            continue
        _accumulate_pass(
            runtime,
            doc,
            page.second,
            expected_model,
            expected_provider,
            truncation_token_threshold,
            2,
        )
        for label in detect_anomalies(page.second.transcription):
            anomalies["pass2"][label] += 1
            doc["anomalies"] += 1
            anomaly_examples.setdefault(f"pass2:{label}", [])
            if len(anomaly_examples[f"pass2:{label}"]) < anomaly_example_limit:
                anomaly_examples[f"pass2:{label}"].append(example_id)

        if (
            page.first.render_pixel_sha256 is not None
            and page.second.render_pixel_sha256 is not None
        ):
            runtime["render_pixel_verified"] += 1
        else:
            runtime["render_legacy_unverified"] += 1

        change = classify_change(page.first.transcription, page.second.transcription)
        taxonomy[change] += 1
        if change != CHANGE_EXACT:
            doc["changed"] += 1
        if change == CHANGE_SUBSTANTIVE:
            doc["substantive"] += 1
            similarity = substantive_similarity(page.first.transcription, page.second.transcription)
            similarities.append(similarity)
            rewrite_candidates.append(
                (similarity, len(page.second.transcription) - len(page.first.transcription),
                 page.document_id, page.page_index)
            )
        disagreements = legal_span_disagreements(
            page.first.transcription, page.second.transcription
        )
        for category, spans in disagreements.items():
            doc["legal_disagreements"] += 1
            legal_disagreements.append(
                {
                    "document_id": page.document_id,
                    "page_index": page.page_index,
                    "category": category,
                    "first_only": spans["first_only"],
                    "second_only": spans["second_only"],
                }
            )

    similarities.sort()
    rewrite_candidates.sort(key=lambda item: item[0])
    largest_rewrites = [
        {
            "document_id": document_id,
            "page_index": page_index,
            "similarity": round(similarity, 4),
            "length_delta": length_delta,
        }
        for similarity, length_delta, document_id, page_index in rewrite_candidates[
            :largest_rewrite_limit
        ]
    ]
    return {
        "page_count": len(pages),
        "missing_second_pass": missing_second_pass,
        "source_classifications": dict(sorted(classifications.items())),
        "change_taxonomy": {name: taxonomy.get(name, 0) for name in CHANGE_CLASSES},
        "substantive": {
            "count": len(similarities),
            "similarity": {
                "min": similarities[0] if similarities else None,
                "p25": percentile(similarities, 0.25) if similarities else None,
                "median": percentile(similarities, 0.5) if similarities else None,
                "p75": percentile(similarities, 0.75) if similarities else None,
                "max": similarities[-1] if similarities else None,
            },
            "largest_rewrites": largest_rewrites,
        },
        "anomalies": {
            "pass1": {name: anomalies["pass1"].get(name, 0) for name in ANOMALIES},
            "pass2": {name: anomalies["pass2"].get(name, 0) for name in ANOMALIES},
        },
        "anomaly_examples": dict(sorted(anomaly_examples.items())),
        "legal_disagreements": legal_disagreements,
        "runtime": runtime,
        "documents": sorted(documents.values(), key=lambda item: item["document_id"]),
    }


def _accumulate_pass(
    runtime: dict[str, Any],
    document: dict[str, Any],
    record: PassEvidence,
    expected_model: str,
    expected_provider: str,
    truncation_token_threshold: int,
    pass_number: int,
) -> None:
    document["cost_usd"] += record.cost_usd
    runtime["cost_total_usd"] += record.cost_usd
    if pass_number == 1:
        runtime["cost_pass1_usd"] += record.cost_usd
    else:
        runtime["cost_pass2_usd"] += record.cost_usd
    runtime["completion_tokens_total"] += record.completion_tokens
    runtime["latency_seconds_total"] += record.latency_seconds
    if record.completion_tokens >= truncation_token_threshold:
        runtime["truncation_suspects"] += 1
    if record.returned_model != expected_model:
        runtime["returned_model_mismatch"] += 1
    if not _providers_match(expected_provider, record.returned_provider):
        runtime["returned_provider_mismatch"] += 1


def _providers_match(expected: str, returned: str) -> bool:
    expected_folded, returned_folded = expected.casefold(), returned.casefold()
    if not returned_folded:
        return False
    return returned_folded in expected_folded or expected_folded in returned_folded
