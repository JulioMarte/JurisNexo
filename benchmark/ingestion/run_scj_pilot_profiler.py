from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jurisnexo.ingestion.scj_layouts import LayoutDetectionStatus
from jurisnexo.ingestion.scj_metadata import MetadataObservation, parse_scj_page_metadata
from jurisnexo.ingestion.scj_segmentation import CaseSegment, segment_scj_pages


_DECLARED_DECISIONS_RE = re.compile(
    r"(?is)cuenta\s+con\s+(?P<count>\d{1,3})\s+(?:decisiones|sentencias)"
)


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


def _declared_decision_count(pages: list[str]) -> int | None:
    # Front matter is the only place this compilation-level count is useful.
    # It is a diagnostic, not ground truth for individual boundaries.
    front_matter = "\n".join(pages[:12])
    match = _DECLARED_DECISIONS_RE.search(front_matter)
    return int(match.group("count")) if match is not None else None


def _profile_segment(segment: CaseSegment, pages: list[str], ordinal: int) -> dict[str, Any]:
    by_field: dict[str, list[MetadataObservation]] = defaultdict(list)
    diagnostics = list(segment.diagnostics)

    for page_number in range(segment.start_page, segment.end_page + 1):
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
    dockets = sorted(
        {
            observation.normalized_text
            for observation in by_field.get("docket_number", [])
            if observation.normalized_text is not None
        }
    )
    organs = sorted(
        {
            observation.normalized_text
            for observation in by_field.get("court_organ", [])
            if observation.normalized_text is not None
        }
    )

    if len(decision_numbers) > 1:
        diagnostics.append("multiple_decision_numbers_observed")
    if len(decision_dates) > 1:
        diagnostics.append("multiple_decision_dates_observed")
    if len(organs) > 1:
        diagnostics.append("multiple_court_organs_observed")

    return {
        "ordinal": ordinal,
        "layout": segment.family.value,
        "signature_key": segment.signature_key,
        "start_page": segment.start_page,
        "end_page": segment.end_page,
        "page_count": segment.end_page - segment.start_page + 1,
        "status": segment.status.value,
        "fields_present": sorted(by_field),
        "decision_numbers_observed": decision_numbers,
        "dockets_observed": dockets,
        "decision_dates_observed": decision_dates,
        "court_organs_observed": organs,
        "diagnostics": sorted(set(diagnostics)),
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
        # Deterministic spacing keeps reruns stable. Layout-level stratification
        # will be added when the gold annotation workflow is introduced.
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
            "parser_dockets": profile["dockets_observed"],
            "parser_decision_dates": profile["decision_dates_observed"],
            "parser_court_organs": profile["court_organs_observed"],
            "parser_diagnostics": profile["diagnostics"],
            "gold_boundary_valid": None,
            "gold_decision_number": None,
            "gold_docket_numbers": None,
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
    segments, detections = segment_scj_pages(pages)
    profiles = [
        _profile_segment(segment, pages, index + 1)
        for index, segment in enumerate(segments)
    ]

    coverage = Counter[str]()
    layouts = Counter[str]()
    diagnostics = Counter[str]()
    for profile in profiles:
        layouts[profile["layout"]] += 1
        for field in profile["fields_present"]:
            coverage[field] += 1
        for diagnostic in profile["diagnostics"]:
            diagnostics[diagnostic] += 1

    declared = _declared_decision_count(pages)
    recognized_pages = sum(
        detection.status is LayoutDetectionStatus.RECOGNIZED for detection in detections
    )
    ambiguous_pages = sum(
        detection.status is LayoutDetectionStatus.AMBIGUOUS for detection in detections
    )
    unknown_pages = sum(
        detection.status is LayoutDetectionStatus.UNKNOWN for detection in detections
    )

    report = {
        "source": {
            "filename": args.pdf.name,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "byte_size": len(pdf_bytes),
            "page_count": len(pages),
        },
        "methodology": {
            "classification": "coverage_profile_not_gold_accuracy",
            "parser": "jurisnexo.ingestion.scj_layouts + scj_segmentation + scj_metadata",
            "boundary_method": "publication-aware production segmenter",
            "review_sample_limit": args.review_limit,
        },
        "counts": {
            "case_segments": len(segments),
            "declared_decisions_front_matter": declared,
            "detected_minus_declared": (
                len(segments) - declared if declared is not None else None
            ),
            "recognized_pages": recognized_pages,
            "ambiguous_pages": ambiguous_pages,
            "unknown_pages": unknown_pages,
            "segments_with_multiple_decision_dates": sum(
                1
                for profile in profiles
                if "multiple_decision_dates_observed" in profile["diagnostics"]
            ),
        },
        "layouts": dict(sorted(layouts.items())),
        "diagnostics": dict(sorted(diagnostics.items())),
        "coverage": {
            field: {
                "segments": count,
                "rate": count / len(profiles) if profiles else 0.0,
            }
            for field, count in sorted(coverage.items())
        },
        "profiles": profiles,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

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
                "diagnostics": report["diagnostics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
