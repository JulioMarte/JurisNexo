from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SCJLayoutFamily(StrEnum):
    PRINCIPALES_2023_2024_SENTENCE = "principales_2023_2024_sentence"
    PRINCIPALES_2023_2024_RESOLUTION = "principales_2023_2024_resolution"
    PRINCIPALES_2025_PRIMERA_SALA = "principales_2025_primera_sala"
    PRINCIPALES_2025_SEGUNDA_SALA = "principales_2025_segunda_sala"
    PRINCIPALES_2025_TERCERA_SALA = "principales_2025_tercera_sala"
    PRINCIPALES_2025_PLENO_RESOLUTION = "principales_2025_pleno_resolution"
    UNKNOWN = "unknown"


class LayoutDetectionStatus(StrEnum):
    RECOGNIZED = "recognized"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PageLayoutDetection:
    page_number: int
    family: SCJLayoutFamily
    status: LayoutDetectionStatus
    signature_key: str | None
    primary_decision_number: str | None = None
    header_date: date | None = None
    evidence: tuple[str, ...] = ()


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

_FORMAL_SENTENCE_RE = re.compile(
    rf"(?im)^\s*(?:\d{{1,3}}[-.)]\s*)?SENTENCIA\s+DEL\s+"
    rf"(?P<day>\d{{1,2}})\s+DE\s+(?P<month>{_MONTH})\s+DE\s+"
    rf"(?P<year>\d{{4}})\s*,?\s*N[ÚU]M\.?\s*"
    r"(?P<number>SCJ-[A-Z]{2,4}-\d{2}-\d{3,6})\s*$"
)
_FORMAL_DATED_RESOLUTION_RE = re.compile(
    rf"(?im)^\s*(?:\d{{1,3}}[-.)]\s*)?RESOLUCI[ÓO]N\s+DEL\s+"
    rf"(?P<day>\d{{1,2}})\s+DE\s+(?P<month>{_MONTH})\s+DE\s+"
    rf"(?P<year>\d{{4}})\s*,?\s*N[ÚU]M\.?\s*"
    r"(?P<number>SCJ-[A-Z]{2,4}-\d{2}-\d{2,6})\s*$"
)
# Deliberately case-sensitive. The old publication starts are typographically
# upper-case; body citations such as "resolución núm." must not become boundaries.
_FORMAL_RESOLUTION_RE = re.compile(
    r"(?m)^\s*RESOLUCI[ÓO]N\s+N[ÚU]M\.?\s*(?P<number>[A-Z0-9.-]+)\s*,?\s*"
    r"(?P<title>[^\n]*)$"
)
_MODERN_RESOLUTION_RE = re.compile(
    r"(?im)^\s*Resoluci[oó]n\s+n[úu]m\.?\s*(?P<number>[A-Z0-9.-]+)\s*$"
)
_SCJ_PS_RE = re.compile(r"\bSCJ-PS-\d{2}-\d{3,6}\b", re.IGNORECASE)
_SCJ_ANY_RE = re.compile(r"\bSCJ-[A-Z]{2,4}-\d{2}-\d{2,6}\b", re.IGNORECASE)
_EXP_2025_RE = re.compile(
    r"(?im)^\s*Exp(?:s)?\.?\s*(?:n[úu]m(?:s)?\.?)?\s*:?\s*(?P<value>[^\n\r]+?)\s*$"
)
_SS_REC_RE = re.compile(r"(?im)^\s*R(?:c|ec)s?\.?\s*:?\s*(?P<value>[^\n\r]+?)\s*$")
_DATE_LABEL_RE = re.compile(
    rf"(?im)^\s*Fecha\s*:\s*(?P<day>\d{{1,2}})\s+de\s+"
    rf"(?P<month>{_MONTH})\s+de\s+(?P<year>\d{{4}})\s*$"
)
_MATTER_RE = re.compile(r"(?im)^\s*Materia\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_DECISION_RE = re.compile(r"(?im)^\s*Decisi[oó]n\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_PARTIES_RE = re.compile(r"(?im)^\s*Partes\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_RAPPORTEUR_RE = re.compile(r"(?im)^\s*Ponente\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_SENTENCE_NUM_RE = re.compile(
    r"(?im)^\s*Sentencia\s+n[úu]m\.?\s*"
    r"(?P<number>SCJ-[A-Z]{2,4}-\d{2}-\d{2,6})\s*$"
)
_FULL_COURT_EXP_RE = re.compile(
    r"(?im)^\s*Expediente\s+n[úu]m\.?\s*:\s*(?P<value>[^\n\r]+?)\s*$"
)
_PARTY_ROLE_RE = re.compile(
    r"(?im)^\s*(?:Recurrente|Recurrido)[^:\n]{0,100}:\s*.+$"
)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _parse_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), _MONTHS[month.lower()], int(day))
    except ValueError:
        return None


def _unknown(page_number: int) -> PageLayoutDetection:
    return PageLayoutDetection(
        page_number=page_number,
        family=SCJLayoutFamily.UNKNOWN,
        status=LayoutDetectionStatus.UNKNOWN,
        signature_key=None,
    )


def detect_scj_page_layout(text: str, *, page_number: int) -> PageLayoutDetection:
    """Classify one physical SCJ compilation page without inventing identity.

    Old 2023/2024 compilations use one formal case-start heading. The observed
    2025 generation uses repeated structured headers. These grammars are kept
    separate so a citation cannot silently become a case boundary.
    """
    if page_number <= 0:
        raise ValueError("page_number must be positive")

    formal = _FORMAL_SENTENCE_RE.search(text)
    if formal is not None:
        parsed_date = _parse_date(
            formal.group("day"), formal.group("month"), formal.group("year")
        )
        number = formal.group("number").upper()
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2023_2024_SENTENCE,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=number,
            primary_decision_number=number,
            header_date=parsed_date,
            evidence=(_normalized(formal.group(0)),),
        )

    dated_resolution = _FORMAL_DATED_RESOLUTION_RE.search(text)
    if dated_resolution is not None:
        parsed_date = _parse_date(
            dated_resolution.group("day"),
            dated_resolution.group("month"),
            dated_resolution.group("year"),
        )
        number = dated_resolution.group("number").upper()
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=number,
            primary_decision_number=number,
            header_date=parsed_date,
            evidence=(_normalized(dated_resolution.group(0)),),
        )

    formal_resolution = _FORMAL_RESOLUTION_RE.search(text)
    if formal_resolution is not None:
        number = _normalized(formal_resolution.group("number")).upper()
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=number,
            evidence=(_normalized(formal_resolution.group(0)),),
        )

    header = text[:2400]
    exp = _EXP_2025_RE.search(header)
    matter = _MATTER_RE.search(header)
    decision = _DECISION_RE.search(header)

    # Tercera Sala has the strongest structured grammar. Test it before an
    # SCJ-PS reference so a cited Primera Sala decision cannot split the case.
    if (
        exp is not None
        and matter is not None
        and decision is not None
        and _PARTY_ROLE_RE.search(header)
    ):
        primary = next(
            (
                match.group(0).upper()
                for match in _SCJ_ANY_RE.finditer(header)
                if match.group(0).upper().startswith("SCJ-TS-")
            ),
            None,
        )
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2025_TERCERA_SALA,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=_normalized(exp.group("value")),
            primary_decision_number=primary,
            evidence=(
                _normalized(exp.group(0)),
                _normalized(matter.group(0)),
                _normalized(decision.group(0)),
            ),
        )

    date_match = _DATE_LABEL_RE.search(header)
    recurrent = _SS_REC_RE.search(header)
    sentence_number = _SENTENCE_NUM_RE.search(header)
    if exp is not None and recurrent is not None and date_match is not None:
        parsed_date = _parse_date(
            date_match.group("day"), date_match.group("month"), date_match.group("year")
        )
        primary = sentence_number.group("number").upper() if sentence_number else None
        key = " | ".join(
            (
                _normalized(exp.group("value")),
                _normalized(recurrent.group("value")),
                _normalized(date_match.group(0)),
            )
        )
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2025_SEGUNDA_SALA,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=key,
            primary_decision_number=primary,
            header_date=parsed_date,
            evidence=(
                _normalized(exp.group(0)),
                _normalized(recurrent.group(0)),
                _normalized(date_match.group(0)),
            ),
        )

    modern_resolution = _MODERN_RESOLUTION_RE.search(header)
    full_court_exp = _FULL_COURT_EXP_RE.search(header)
    if modern_resolution is not None and full_court_exp is not None:
        key = (
            f"{_normalized(modern_resolution.group('number'))} | "
            f"{_normalized(full_court_exp.group('value'))}"
        )
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2025_PLENO_RESOLUTION,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=key,
            evidence=(
                _normalized(modern_resolution.group(0)),
                _normalized(full_court_exp.group(0)),
            ),
        )

    ps_match = _SCJ_PS_RE.search(header[:700])
    labels = tuple(
        name
        for name, pattern in (
            ("partes", _PARTIES_RE),
            ("materia", _MATTER_RE),
            ("decision", _DECISION_RE),
            ("ponente", _RAPPORTEUR_RE),
        )
        if pattern.search(header) is not None
    )
    if ps_match is not None and len(labels) >= 3:
        number = ps_match.group(0).upper()
        return PageLayoutDetection(
            page_number=page_number,
            family=SCJLayoutFamily.PRINCIPALES_2025_PRIMERA_SALA,
            status=LayoutDetectionStatus.RECOGNIZED,
            signature_key=number,
            primary_decision_number=number,
            evidence=labels,
        )

    return _unknown(page_number)
