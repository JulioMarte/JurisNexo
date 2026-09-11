from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.ingestion.scj_metadata import parse_scj_page_metadata


_DECISION_NUMBER_RE = re.compile(r"\bSCJ-[A-Z]{2,4}-\d{2}-\d{3,6}\b", re.IGNORECASE)
_HEADER_LABEL_RE = re.compile(
    r"(?im)^\s*(Expediente\s+n[úu]m\.?|Partes|Materia|Decisi[oó]n|Ponente)\s*[:\-]?"
)


@dataclass(frozen=True, slots=True)
class HeaderCandidate:
    decision_number: str
    global_start: int
    page_number: int
    labels_nearby: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    field_name: str
    method_name: str
    page_number: int
    global_start: int
    global_end: int
    raw_value: str
    normalized_text: str | None
    normalized_date: str | None


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


def _page_offsets(pages: list[str]) -> tuple[str, list[int]]:
    offsets: list[int] = []
    parts: list[str] = []
    position = 0
    for page in pages:
        offsets.append(position)
        parts.append(page)
        position += len(page) + 1
    return "\f".join(parts), offsets


def _page_for_offset(offsets: list[int], position: int) -> int:
    low = 0
    high = len(offsets)
    while low + 1 < high:
        mid = (low + high) // 2
        if offsets[mid] <= position:
            low = mid
        else:
            high = mid
    return low + 1


def _find_header_candidates(document: str, offsets: list[int]) -> list[HeaderCandidate]:
    candidates: list[HeaderCandidate] = []
    seen: set[tuple[str, int]] = set()

    for match in _DECISION_NUMBER_RE.finditer(document):
        # A case header should be followed closely by several structured labels.
        # This intentionally sacrifices recall to avoid treating citations to
        # other SCJ decisions in the body as new case boundaries.
        window = document[match.end() : match.end() + 1800]
        labels = tuple(
            label.group(1).lower().replace("ú", "u")
            for label in _HEADER_LABEL_RE.finditer(window)
        )
        unique_labels = tuple(dict.fromkeys(labels))
        if len(unique_labels) < 3:
            continue

        decision_number = match.group(0).upper()
        page_number = _page_for_offset(offsets, match.start())
        identity = (decision_number, match.start())
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(
            HeaderCandidate(
                decision_number=decision_number,
                global_start=match.start(),
                page_number=page_number,
                labels_nearby=unique_labels,
            )
        )

    return candidates


def _collect_observations(pages: list[str], offsets: list[int]) -> list[ObservationRecord]:
    records: list[ObservationRecord] = []
    for index, page in enumerate(pages):
        page_number = index + 1
        page_offset = offsets[index]
        for observation in parse_scj_page_metadata(page, page_number=page_number):
            records.append(
                ObservationRecord(
                    field_name=observation.field_name,
                    method_name=observation.method_name,
                    page_number=page_number,
                    global_start=page_offset + observation.char_start,
                    global_end=page_offset + observation.char_end,
                    raw_value=observation.raw_value,
                    normalized_text=observation.normalized_text,
                    normalized_date=(
                        observation.normalized_date.isoformat()
                        if observation.normalized_date is not None
                        else None
                    ),
                )
            )
    return records


def _case_profiles(
    candidates: list[HeaderCandidate],
    observations: list[ObservationRecord],
    document_length: int,
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    observation_index = 0
    ordered_observations = sorted(observations, key=lambda item: item.global_start)

    for index, candidate in enumerate(candidates):
        end = (
            candidates[index + 1].global_start
            if index + 1 < len(candidates)
            else document_length
        )
        while (
            observation_index < len(ordered_observations)
            and ordered_observations[observation_index].global_start < candidate.global_start
        ):
            observation_index += 1

        cursor = observation_index
        case_observations: list[ObservationRecord] = []
        while (
            cursor < len(ordered_observations)
            and ordered_observations[cursor].global_start < end
        ):
            case_observations.append(ordered_observations[cursor])
            cursor += 1

        by_field: dict[str, list[ObservationRecord]] = defaultdict(list)
        for observation in case_observations:
            by_field[observation.field_name].append(observation)

        decision_dates = sorted(
            {
                observation.normalized_date
                for observation in by_field.get("decision_date_candidate", [])
                if observation.normalized_date is not None
            }
        )
        decision_numbers = sorted(
            {
                observation.normalized_text
                for observation in by_field.get("decision_number", [])
                if observation.normalized_text is not None
            }
        )

        profiles.append(
            {
                "ordinal": index + 1,
                "header_decision_number": candidate.decision_number,
                "start_page": candidate.page_number,
                "end_page": (
                    _page_for_offset(
                        [0], 0
                    )  # overwritten below; keeps mypy/pyright shape simple
                ),
                "labels_nearby": list(candidate.labels_nearby),
                "fields_present": sorted(by_field),
                "decision_numbers_observed": decision_numbers,
                "decision_dates_observed": decision_dates,
                "decision_date_conflict": len(decision_dates) > 1,
                "observation_count": len(case_observations),
            }
        )

    # Derive end pages from the next header. This remains approximate until a
    # production case-boundary parser is implemented and manually evaluated.
    for index, profile in enumerate(profiles):
        next_start_page = (
            candidates[index + 1].page_number
            if index + 1 < len(candidates)
            else None
        )
        profile["end_page"] = (
            max(profile["start_page"], next_start_page - 1)
            if next_start_page is not None
            else None
        )
    return profiles


def _review_sample(profiles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not profiles:
        return []
    if len(profiles) <= limit:
        chosen = profiles
    else:
        # Deterministic even-spacing makes the sample reproducible and avoids
        # cherry-picking only early pages or only one chamber prefix.
        indexes = {
            round(index * (len(profiles) - 1) / (limit - 1))
            for index in range(limit)
        }
        chosen = [profiles[index] for index in sorted(indexes)]

    return [
        {
            "ordinal": profile["ordinal"],
            "header_decision_number": profile["header_decision_number"],
            "start_page": profile["start_page"],
            "parser_fields_present": profile["fields_present"],
            "parser_decision_dates": profile["decision_dates_observed"],
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
    document, offsets = _page_offsets(pages)
    candidates = _find_header_candidates(document, offsets)
    observations = _collect_observations(pages, offsets)
    profiles = _case_profiles(candidates, observations, len(document))

    coverage = Counter()
    for profile in profiles:
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
            "header_candidate_rule": "SCJ decision number followed by >=3 structured labels within 1800 chars",
            "review_sample_limit": args.review_limit,
        },
        "counts": {
            "header_candidates": len(candidates),
            "unique_header_decision_numbers": len({c.decision_number for c in candidates}),
            "all_metadata_observations": len(observations),
            "cases_with_multiple_decision_dates": sum(
                1 for profile in profiles if profile["decision_date_conflict"]
            ),
        },
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

    print(json.dumps({"counts": report["counts"], "coverage": report["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
