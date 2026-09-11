from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jurisnexo.ingestion.scj_metadata import parse_scj_page_metadata


_SCJ_PS_RE = re.compile(r"\bSCJ-PS-\d{2}-\d{3,6}\b", re.IGNORECASE)
_SCJ_ANY_RE = re.compile(r"\bSCJ-[A-Z]{2,4}-\d{2}-\d{3,6}\b", re.IGNORECASE)
_SS_EXP_RE = re.compile(r"(?im)^\s*Exp\.?\s*:?\s*(?P<value>[^\n\r]+?)\s*$")
_SS_REC_RE = re.compile(r"(?im)^\s*R(?:c|ec)s?\.?\s*:?\s*(?P<value>[^\n\r]+?)\s*$")
_SS_DATE_RE = re.compile(r"(?im)^\s*Fecha\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_TS_EXP_RE = re.compile(
    r"(?im)^\s*Exps?\.\s*n[úu]ms?\.?\s*:\s*(?P<value>[^\n\r]+?)\s*$"
)
_TS_PARTY_RE = re.compile(r"(?im)^\s*(Recurrente|Recurrido|Solicitud)\b")
_MATTER_RE = re.compile(r"(?im)^\s*Materia\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_DECISION_RE = re.compile(r"(?im)^\s*Decisi[oó]n\s*:\s*(?P<value>[^\n\r]+?)\s*$")
_RESOLUTION_RE = re.compile(
    r"(?im)^\s*Resoluci[oó]n\s+n[úu]m\.?\s*(?P<value>[^\n\r]+?)\s*$"
)
_FULL_COURT_EXP_RE = re.compile(
    r"(?im)^\s*Expediente\s+n[úu]m\.?:\s*(?P<value>[^\n\r]+?)\s*$"
)


@dataclass(frozen=True, slots=True)
class PageSignature:
    layout: str
    key: str
    header_date_text: str | None = None


@dataclass(frozen=True, slots=True)
class CaseRun:
    signature: PageSignature
    start_page: int
    end_page: int


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _extract_pages(pdf_path: Path) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as output:
        text_path = Path(output.name)
    try:
        subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), str(text_path)],
            check=True,
        )
        text = text_path.read_text(encoding="utf-8", errors="replace")
    finally:
        text_path.unlink(missing_ok=True)

    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _page_signature(page: str) -> PageSignature | None:
    # SCJ compilations repeat a stable case header on almost every page. Prefer
    # structured chamber layouts over SCJ-number matches: a Tercera Sala page
    # can cite a Primera Sala decision near the top without changing cases.
    header = page[:1800]

    ts_exp = _TS_EXP_RE.search(header)
    if (
        ts_exp is not None
        and _MATTER_RE.search(header)
        and _DECISION_RE.search(header)
        and _TS_PARTY_RE.search(header)
    ):
        return PageSignature("tercera_sala", _normalized(ts_exp.group("value")))

    ss_exp = _SS_EXP_RE.search(header[:700])
    ss_rec = _SS_REC_RE.search(header[:900])
    ss_date = _SS_DATE_RE.search(header[:900])
    if ss_exp is not None and ss_rec is not None and ss_date is not None:
        return PageSignature(
            "segunda_sala",
            " | ".join(
                (
                    _normalized(ss_exp.group("value")),
                    _normalized(ss_rec.group("value")),
                    _normalized(ss_date.group("value")),
                )
            ),
            _normalized(ss_date.group("value")),
        )

    resolution = _RESOLUTION_RE.search(header)
    full_court_exp = _FULL_COURT_EXP_RE.search(header)
    if resolution is not None and full_court_exp is not None:
        return PageSignature(
            "pleno_or_resolution",
            f"{_normalized(resolution.group('value'))} | {_normalized(full_court_exp.group('value'))}",
        )

    ps_match = _SCJ_PS_RE.search(header[:500])
    if ps_match is not None:
        return PageSignature("primera_sala", ps_match.group(0).upper())

    return None


def _case_runs(pages: list[str]) -> tuple[list[CaseRun], list[PageSignature | None]]:
    signatures = [_page_signature(page) for page in pages]
    runs: list[CaseRun] = []
    active: PageSignature | None = None
    active_start = 0

    for page_number, signature in enumerate(signatures, start=1):
        if signature is None:
            continue
        if active is None:
            active = signature
            active_start = page_number
            continue
        if signature != active:
            runs.append(CaseRun(active, active_start, page_number - 1))
            active = signature
            active_start = page_number

    if active is not None:
        runs.append(CaseRun(active, active_start, len(pages)))
    return runs, signatures


def _profile_case(run: CaseRun, pages: list[str], ordinal: int) -> dict[str, Any]:
    by_field: dict[str, list[Any]] = defaultdict(list)
    for page_number in range(run.start_page, run.end_page + 1):
        for observation in parse_scj_page_metadata(
            pages[page_number - 1], page_number=page_number
        ):
            by_field[observation.field_name].append(observation)

    decision_numbers = sorted(
        {
            observation.normalized_text
            for observation in by_field.get("decision_number", [])
            if observation.normalized_text is not None
        }
    )
    decision_dates = sorted(
        {
            observation.normalized_date.isoformat()
            for observation in by_field.get("decision_date_candidate", [])
            if observation.normalized_date is not None
        }
    )

    first_page_scj_numbers = sorted(
        {match.group(0).upper() for match in _SCJ_ANY_RE.finditer(pages[run.start_page - 1])}
    )

    return {
        "ordinal": ordinal,
        "layout": run.signature.layout,
        "signature_key": run.signature.key,
        "start_page": run.start_page,
        "end_page": run.end_page,
        "page_count": run.end_page - run.start_page + 1,
        "header_date_text": run.signature.header_date_text,
        "first_page_scj_numbers": first_page_scj_numbers,
        "fields_present": sorted(by_field),
        "decision_numbers_observed": decision_numbers,
        "decision_dates_observed": decision_dates,
        "decision_date_conflict": len(decision_dates) > 1,
        "observation_count": sum(len(values) for values in by_field.values()),
    }


def _review_sample(profiles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not profiles:
        return []
    if len(profiles) <= limit:
        chosen = profiles
    elif limit <= 1:
        chosen = [profiles[0]]
    else:
        indexes = {
            round(index * (len(profiles) - 1) / (limit - 1))
            for index in range(limit)
        }
        chosen = [profiles[index] for index in sorted(indexes)]

    return [
        {
            "ordinal": profile["ordinal"],
            "layout": profile["layout"],
            "signature_key": profile["signature_key"],
            "start_page": profile["start_page"],
            "end_page": profile["end_page"],
            "parser_decision_numbers": profile["decision_numbers_observed"],
            "parser_decision_dates": profile["decision_dates_observed"],
            "header_date_text": profile["header_date_text"],
            "gold_boundary_valid": None,
            "gold_decision_number": None,
            "gold_docket_number": None,
            "gold_decision_date": None,
            "gold_court_organ": None,
            "review_notes": None,
        }
        for profile in chosen
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-sample", type=Path, required=True)
    parser.add_argument("--review-limit", type=int, default=100)
    args = parser.parse_args()

    pdf_bytes = args.pdf.read_bytes()
    pages = _extract_pages(args.pdf)
    runs, page_signatures = _case_runs(pages)
    profiles = [_profile_case(run, pages, index + 1) for index, run in enumerate(runs)]

    coverage = Counter()
    layouts = Counter()
    for profile in profiles:
        layouts[profile["layout"]] += 1
        for field in profile["fields_present"]:
            coverage[field] += 1

    report = {
        "source": {
            "filename": args.pdf.name,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "byte_size": len(pdf_bytes),
            "page_count": len(pages),
        },
        "methodology": {
            "classification": "coverage_profile_not_gold_accuracy",
            "boundary_method": "contiguous runs of repeated structured page-header signatures",
            "review_sample_limit": args.review_limit,
        },
        "counts": {
            "case_runs": len(runs),
            "unique_signatures": len({(run.signature.layout, run.signature.key) for run in runs}),
            "pages_with_recognized_header": sum(signature is not None for signature in page_signatures),
            "pages_without_recognized_header": sum(signature is None for signature in page_signatures),
            "cases_with_multiple_decision_dates": sum(
                1 for profile in profiles if profile["decision_date_conflict"]
            ),
        },
        "layouts": dict(sorted(layouts.items())),
        "coverage": {
            field: {
                "cases": count,
                "rate": count / len(profiles) if profiles else 0.0,
            }
            for field, count in sorted(coverage.items())
        },
        "profiles": profiles,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    sample = _review_sample(profiles, args.review_limit)
    args.review_sample.parent.mkdir(parents=True, exist_ok=True)
    with args.review_sample.open("w", encoding="utf-8") as handle:
        for row in sample:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        json.dumps(
            {
                "source": report["source"],
                "counts": report["counts"],
                "layouts": report["layouts"],
                "coverage": report["coverage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
