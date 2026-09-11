from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ObservationValueType(StrEnum):
    TEXT = "text"
    DATE = "date"
    IDENTIFIER = "identifier"


@dataclass(frozen=True, slots=True)
class MetadataObservation:
    field_name: str
    value_type: ObservationValueType
    raw_value: str
    method_name: str
    page_number: int
    char_start: int
    char_end: int
    normalized_text: str | None = None
    normalized_date: date | None = None

    @property
    def observation_key(self) -> str:
        payload = "\x1f".join(
            (
                self.field_name,
                self.method_name,
                str(self.page_number),
                str(self.char_start),
                str(self.char_end),
                self.raw_value,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_DECISION_NUMBER_RE = re.compile(r"\bSCJ-[A-Z]{2,4}-\d{2}-\d{3,6}\b", re.IGNORECASE)
_EXPEDIENTE_RE = re.compile(
    r"(?im)^\s*Expediente\s+n[úu]m\.?\s*[:\-]?\s*(?P<value>[^\n\r]+?)\s*$"
)
_LABELED_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "parties",
        re.compile(r"(?im)^\s*Partes\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_parties_v1",
    ),
    (
        "matter",
        re.compile(r"(?im)^\s*Materia\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_matter_v1",
    ),
    (
        "decision_summary",
        re.compile(r"(?im)^\s*Decisi[oó]n\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_decision_v1",
    ),
    (
        "rapporteur",
        re.compile(r"(?im)^\s*Ponente\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_rapporteur_v1",
    ),
)
_SPANISH_DATE_RE = re.compile(
    r"(?i)\ben\s+fecha\s+(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+"
    r"de\s+(?P<year>\d{4})\b"
)

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _parse_spanish_date_match(match: re.Match[str]) -> date | None:
    month = _MONTHS[match.group("month").lower()]
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def parse_scj_page_metadata(text: str, *, page_number: int) -> list[MetadataObservation]:
    """Extract only high-precision metadata patterns observed in SCJ compilations.

    This function deliberately does not reconcile observations into canonical case fields.
    It emits evidence-bearing observations whose promotion is a separate concern.
    """

    if page_number <= 0:
        raise ValueError("page_number must be positive")

    observations: list[MetadataObservation] = []

    for match in _DECISION_NUMBER_RE.finditer(text):
        raw = match.group(0)
        observations.append(
            MetadataObservation(
                field_name="decision_number",
                value_type=ObservationValueType.IDENTIFIER,
                raw_value=raw,
                normalized_text=raw.upper(),
                method_name="scj_decision_number_v1",
                page_number=page_number,
                char_start=match.start(),
                char_end=match.end(),
            )
        )

    for match in _EXPEDIENTE_RE.finditer(text):
        raw = match.group("value").strip()
        observations.append(
            MetadataObservation(
                field_name="docket_number",
                value_type=ObservationValueType.IDENTIFIER,
                raw_value=raw,
                normalized_text=_collapse_whitespace(raw),
                method_name="scj_labeled_docket_v1",
                page_number=page_number,
                char_start=match.start("value"),
                char_end=match.end("value"),
            )
        )

    for field_name, pattern, method_name in _LABELED_TEXT_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group("value").strip()
            observations.append(
                MetadataObservation(
                    field_name=field_name,
                    value_type=ObservationValueType.TEXT,
                    raw_value=raw,
                    normalized_text=_collapse_whitespace(raw),
                    method_name=method_name,
                    page_number=page_number,
                    char_start=match.start("value"),
                    char_end=match.end("value"),
                )
            )

    for match in _SPANISH_DATE_RE.finditer(text):
        parsed = _parse_spanish_date_match(match)
        if parsed is None:
            continue
        observations.append(
            MetadataObservation(
                field_name="decision_date_candidate",
                value_type=ObservationValueType.DATE,
                raw_value=match.group(0),
                normalized_date=parsed,
                method_name="scj_body_date_phrase_v1",
                page_number=page_number,
                char_start=match.start(),
                char_end=match.end(),
            )
        )

    return observations
