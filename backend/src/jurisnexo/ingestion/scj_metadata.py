from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from jurisnexo.ingestion.scj_layouts import SCJLayoutFamily, detect_scj_page_layout


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
_MONTH = "|".join(_MONTHS)
_DECISION_NUMBER_RE = re.compile(r"\bSCJ-[A-Z]{2,4}-\d{2}-\d{3,6}\b", re.IGNORECASE)
_DOCKET_LINE_RE = re.compile(
    r"(?im)^\s*(?:Expediente\s+n[úu]m\.?|Exp(?:s)?\.?\s*(?:n[úu]m(?:s)?\.?)?)"
    r"\s*:?\s*(?P<value>[^\n\r]+?)\s*$"
)
_DOCKET_TOKEN_RE = re.compile(
    r"\b[A-Z0-9]{1,10}(?:-[A-Z0-9]{1,14}){1,}\b", re.IGNORECASE
)
_LABELED_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "parties",
        re.compile(r"(?im)^\s*Partes\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_parties_v2",
    ),
    (
        "matter",
        re.compile(r"(?im)^\s*Materia\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_matter_v2",
    ),
    (
        "decision_summary",
        re.compile(r"(?im)^\s*Decisi[oó]n\s*:\s*(?P<value>[^\n\r]+?)\s*$"),
        "scj_labeled_decision_v2",
    ),
    (
        "rapporteur",
        re.compile(
            r"(?im)^\s*(?:Ponente|Juez\s+ponente)\s*:\s*(?P<value>[^\n\r]+?)\s*$"
        ),
        "scj_labeled_rapporteur_v2",
    ),
)
_PARTY_ROLE_RE = re.compile(
    r"(?im)^\s*(?P<role>Recurrente(?:s|\s+principal|\s+incidental)?|"
    r"Recurrido(?:s|\s+principal|\s+incidental)?)[^:\n]{0,70}:\s*"
    r"(?P<value>[^\n\r]+?)\s*$"
)
_DATE_LABEL_RE = re.compile(
    rf"(?im)^\s*Fecha\s*:\s*(?P<day>\d{{1,2}})\s+de\s+"
    rf"(?P<month>{_MONTH})\s+de\s+(?P<year>\d{{4}})\s*$"
)
_DECISION_FORMULA_RE = re.compile(
    rf"(?is)(?P<date_phrase>\ben\s+fecha\s+(?P<day>\d{{1,2}})\s+"
    rf"(?:del\s+mes\s+de\s+|de\s+)(?P<month>{_MONTH})\s+"
    rf"(?:del\s+año\s+|de\s+)(?P<year>\d{{4}})\b)"
    r"(?=.{0,650}\bdicta(?:n)?\b.{0,100}\b(?:sentencia|resoluci[oó]n)\b)"
)
_OLD_SUMMARY_DATE_RE = re.compile(
    r"(?im)^.*?\b(?P<organ>Primera Sala|Segunda Sala|Tercera Sala|Salas Reunidas|Pleno)"
    r"\.\s*(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})"
    r"\.\s*Decisi[oó]n\s+[íi]ntegra\.\s*$"
)
_ORGAN_BY_PREFIX = {
    "PS": "Primera Sala",
    "SS": "Segunda Sala",
    "TS": "Tercera Sala",
    "SR": "Salas Reunidas",
    "PL": "Pleno",
}


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _spanish_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), _MONTHS[month.lower()], int(day))
    except ValueError:
        return None


def _numeric_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _append_identifier(
    observations: list[MetadataObservation],
    *,
    field_name: str,
    raw: str,
    normalized: str,
    method_name: str,
    page_number: int,
    start: int,
    end: int,
) -> None:
    observations.append(
        MetadataObservation(
            field_name=field_name,
            value_type=ObservationValueType.IDENTIFIER,
            raw_value=raw,
            normalized_text=normalized,
            method_name=method_name,
            page_number=page_number,
            char_start=start,
            char_end=end,
        )
    )


def _append_text(
    observations: list[MetadataObservation],
    *,
    field_name: str,
    raw: str,
    method_name: str,
    page_number: int,
    start: int,
    end: int,
) -> None:
    observations.append(
        MetadataObservation(
            field_name=field_name,
            value_type=ObservationValueType.TEXT,
            raw_value=raw,
            normalized_text=_collapse_whitespace(raw),
            method_name=method_name,
            page_number=page_number,
            char_start=start,
            char_end=end,
        )
    )


def _append_date(
    observations: list[MetadataObservation],
    *,
    raw: str,
    value: date,
    method_name: str,
    page_number: int,
    start: int,
    end: int,
) -> None:
    observations.append(
        MetadataObservation(
            field_name="decision_date_candidate",
            value_type=ObservationValueType.DATE,
            raw_value=raw,
            normalized_date=value,
            method_name=method_name,
            page_number=page_number,
            char_start=start,
            char_end=end,
        )
    )


def _primary_number_position(text: str, number: str) -> tuple[int, int] | None:
    match = re.search(re.escape(number), text, re.IGNORECASE)
    if match is None:
        return None
    return match.start(), match.end()


def parse_scj_page_metadata(text: str, *, page_number: int) -> list[MetadataObservation]:
    """Extract deterministic evidence-bearing metadata from one SCJ page.

    Recognized layout families constrain primary identity extraction so body
    citations do not silently become case metadata. Unknown layouts retain a
    candidate-only decision-number fallback and remain unverified upstream.
    """
    if page_number <= 0:
        raise ValueError("page_number must be positive")

    observations: list[MetadataObservation] = []
    detection = detect_scj_page_layout(text, page_number=page_number)

    if detection.primary_decision_number is not None:
        position = _primary_number_position(text, detection.primary_decision_number)
        if position is not None:
            _append_identifier(
                observations,
                field_name="decision_number",
                raw=text[position[0] : position[1]],
                normalized=detection.primary_decision_number,
                method_name="scj_layout_primary_decision_number_v2",
                page_number=page_number,
                start=position[0],
                end=position[1],
            )
    elif detection.family is SCJLayoutFamily.UNKNOWN:
        for match in _DECISION_NUMBER_RE.finditer(text):
            raw = match.group(0)
            _append_identifier(
                observations,
                field_name="decision_number",
                raw=raw,
                normalized=raw.upper(),
                method_name="scj_unclassified_decision_number_candidate_v1",
                page_number=page_number,
                start=match.start(),
                end=match.end(),
            )

    if detection.primary_decision_number is not None:
        parts = detection.primary_decision_number.split("-")
        if len(parts) >= 2 and parts[1] in _ORGAN_BY_PREFIX:
            position = _primary_number_position(text, detection.primary_decision_number)
            start, end = position if position is not None else (0, 1)
            _append_text(
                observations,
                field_name="court_organ",
                raw=_ORGAN_BY_PREFIX[parts[1]],
                method_name="scj_primary_number_organ_v1",
                page_number=page_number,
                start=start,
                end=end,
            )
    elif detection.family in {
        SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION,
        SCJLayoutFamily.PRINCIPALES_2025_PLENO_RESOLUTION,
    }:
        anchor = max(text.lower().find("resoluci"), 0)
        _append_text(
            observations,
            field_name="court_organ",
            raw="Pleno",
            method_name="scj_resolution_layout_organ_v1",
            page_number=page_number,
            start=anchor,
            end=anchor + 1,
        )

    # Emit every docket token separately. Multiple expediente identifiers are
    # evidence-bearing facts and must not be collapsed into one opaque string.
    for line_match in _DOCKET_LINE_RE.finditer(text[:3000]):
        value = line_match.group("value")
        emitted = False
        for token in _DOCKET_TOKEN_RE.finditer(value):
            raw = token.group(0)
            start = line_match.start("value") + token.start()
            end = line_match.start("value") + token.end()
            _append_identifier(
                observations,
                field_name="docket_number",
                raw=raw,
                normalized=raw.upper(),
                method_name="scj_labeled_docket_v2",
                page_number=page_number,
                start=start,
                end=end,
            )
            emitted = True
        if not emitted:
            raw = value.strip()
            if raw:
                _append_identifier(
                    observations,
                    field_name="docket_number",
                    raw=raw,
                    normalized=_collapse_whitespace(raw),
                    method_name="scj_labeled_docket_unparsed_v1",
                    page_number=page_number,
                    start=line_match.start("value"),
                    end=line_match.end("value"),
                )

    for field_name, pattern, method_name in _LABELED_TEXT_PATTERNS:
        for match in pattern.finditer(text[:3500]):
            raw = match.group("value").strip()
            _append_text(
                observations,
                field_name=field_name,
                raw=raw,
                method_name=method_name,
                page_number=page_number,
                start=match.start("value"),
                end=match.end("value"),
            )

    for match in _PARTY_ROLE_RE.finditer(text[:3500]):
        raw = match.group("value").strip()
        role = match.group("role").lower().replace(" ", "_")
        _append_text(
            observations,
            field_name="parties",
            raw=raw,
            method_name=f"scj_party_role_{role}_v1",
            page_number=page_number,
            start=match.start("value"),
            end=match.end("value"),
        )

    emitted_dates: set[date] = set()
    if detection.header_date is not None:
        if detection.family is SCJLayoutFamily.PRINCIPALES_2023_2024_SENTENCE:
            anchor = next(
                (
                    match
                    for match in _DECISION_NUMBER_RE.finditer(text)
                    if match.group(0).upper() == detection.primary_decision_number
                ),
                None,
            )
            start = max(0, anchor.start() - 70) if anchor is not None else 0
            end = anchor.end() if anchor is not None else min(len(text), start + 1)
            raw = text[start:end].strip()
            method = "scj_formal_sentence_heading_date_v1"
        else:
            match = _DATE_LABEL_RE.search(text[:2400])
            start = match.start() if match is not None else 0
            end = match.end() if match is not None else 1
            raw = (
                match.group(0).strip()
                if match is not None
                else detection.header_date.isoformat()
            )
            method = "scj_header_fecha_date_v1"
        _append_date(
            observations,
            raw=raw,
            value=detection.header_date,
            method_name=method,
            page_number=page_number,
            start=start,
            end=end,
        )
        emitted_dates.add(detection.header_date)

    for match in _DECISION_FORMULA_RE.finditer(text):
        parsed = _spanish_date(
            match.group("day"), match.group("month"), match.group("year")
        )
        if parsed is None or parsed in emitted_dates:
            continue
        _append_date(
            observations,
            raw=match.group("date_phrase"),
            value=parsed,
            method_name="scj_decision_formula_date_v2",
            page_number=page_number,
            start=match.start("date_phrase"),
            end=match.end("date_phrase"),
        )
        emitted_dates.add(parsed)

    if detection.family is SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION:
        summary = _OLD_SUMMARY_DATE_RE.search(text[:4000])
        if summary is not None:
            parsed = _numeric_date(
                summary.group("day"), summary.group("month"), summary.group("year")
            )
            if parsed is not None and parsed not in emitted_dates:
                _append_date(
                    observations,
                    raw=summary.group(0).strip(),
                    value=parsed,
                    method_name="scj_compilation_summary_date_v1",
                    page_number=page_number,
                    start=summary.start(),
                    end=summary.end(),
                )

    return observations
