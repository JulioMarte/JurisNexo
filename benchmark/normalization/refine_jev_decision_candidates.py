"""Refine JEV structural hypotheses into evidence-scored decision candidates.

This stage is deterministic. It deliberately does not ask JEV to decide whether its
own earlier hypothesis was correct. It rejects impossible/editorial spans, combines
independent signals, and selects a small contiguous-page pilot set for later model
benchmarks. The output remains candidate evidence, never semantic gold.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

INPUT = Path(os.environ.get("JEV_STRUCTURE_OUTPUT", ".artifacts/jev-structure-pilot.json"))
OUTPUT = Path(os.environ.get("JEV_REFINED_OUTPUT", ".artifacts/jev-refined-candidates.json"))
TARGET_PAGES = int(os.environ.get("JEV_REFINED_TARGET_PAGES", "30"))
MAX_SPAN_PAGES = int(os.environ.get("JEV_REFINED_MAX_SPAN_PAGES", "40"))
MIN_SCORE = float(os.environ.get("JEV_REFINED_MIN_SCORE", "0.72"))

_DECISION_TITLE = re.compile(
    r"\b(?:sentencia|resoluci[oó]n|auto|recurso|casaci[oó]n|habeas|amparo)\b",
    re.IGNORECASE,
)
_EDITORIAL_TITLE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s*)?(?:c[aá]maras?\s+reunidas|primera\s+sala|"
    r"segunda\s+sala|tercera\s+sala|pleno|materia\s+\w+|secci[oó]n|cap[ií]tulo|"
    r"[ií]ndice|sumario|contenido)\s*$",
    re.IGNORECASE,
)


def _prob(candidate: dict[str, Any], side: str, field: str) -> float:
    value = candidate.get(f"{side}_jev") or {}
    return float(value.get(field) or 0.0)


def _fidelity(candidate: dict[str, Any], side: str) -> bool:
    return candidate.get(f"{side}_fidelity") == "aligned"


def _title_kind(title: str) -> str:
    clean = " ".join(title.split())
    if _EDITORIAL_TITLE.match(clean):
        return "editorial"
    if _DECISION_TITLE.search(clean):
        return "decision_like"
    return "unknown"


def _score(candidate: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    problems: list[str] = []
    start = int(candidate["candidate_pdf_start"])
    end_raw = candidate.get("candidate_pdf_end")
    if end_raw is None:
        return 0.0, reasons, ["open_ended_span"]
    end = int(end_raw)
    span_pages = end - start + 1
    if span_pages <= 0:
        return 0.0, reasons, ["non_positive_span"]
    if span_pages > MAX_SPAN_PAGES:
        problems.append("implausibly_long_span")

    title_kind = _title_kind(str(candidate.get("title") or ""))
    if title_kind == "editorial":
        return 0.0, reasons, ["editorial_index_heading"]

    start_judgment = _prob(candidate, "start", "judgment")
    start_boundary = _prob(candidate, "start", "decision_start")
    end_boundary = _prob(candidate, "end", "decision_end")
    end_judgment = _prob(candidate, "end", "judgment")

    score = 0.0
    if title_kind == "decision_like":
        score += 0.18
        reasons.append("decision_like_index_title")
    if start_judgment >= 0.80:
        score += 0.18
        reasons.append("jev_start_is_judgment")
    if start_boundary >= 0.70:
        score += 0.22
        reasons.append("jev_strong_start_boundary")
    if end_boundary >= 0.65:
        score += 0.18
        reasons.append("jev_strong_end_boundary")
    if end_judgment >= 0.60:
        score += 0.08
        reasons.append("jev_end_is_judgment")
    if _fidelity(candidate, "start"):
        score += 0.08
        reasons.append("verified_start_text")
    if _fidelity(candidate, "end"):
        score += 0.06
        reasons.append("verified_end_text")
    if 1 <= span_pages <= 25:
        score += 0.02
        reasons.append("plausible_span_length")

    if start_boundary < 0.35:
        problems.append("weak_start_boundary")
    if end_boundary < 0.35:
        problems.append("weak_end_boundary")
    return min(score, 1.0), reasons, problems


def refine(payload: dict[str, Any]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for document in payload["documents"]:
        identity = {
            "object_key": document["object_key"],
            "document_id": document["document_id"],
            "source_pdf_sha256": document["source_pdf_sha256"],
        }
        for candidate in document["decision_candidates"]:
            score, reasons, problems = _score(candidate)
            item = {
                **identity,
                "title": candidate.get("title"),
                "printed_start_page": candidate.get("printed_start_page"),
                "source_index_page": candidate.get("source_index_page"),
                "candidate_pdf_start": candidate.get("candidate_pdf_start"),
                "candidate_pdf_end": candidate.get("candidate_pdf_end"),
                "confidence_score": round(score, 4),
                "positive_evidence": reasons,
                "problems": problems,
                "start_jev": candidate.get("start_jev"),
                "end_jev": candidate.get("end_jev"),
                "start_fidelity": candidate.get("start_fidelity"),
                "end_fidelity": candidate.get("end_fidelity"),
            }
            if score >= MIN_SCORE and not problems:
                accepted.append(item)
            else:
                rejected.append(item)

    accepted.sort(key=lambda item: (-float(item["confidence_score"]), item["object_key"], int(item["candidate_pdf_start"])))
    selected: list[dict[str, Any]] = []
    selected_pages = 0
    used: set[tuple[str, int]] = set()
    for item in accepted:
        start = int(item["candidate_pdf_start"])
        end = int(item["candidate_pdf_end"])
        pages = list(range(start, end + 1))
        fresh = [page for page in pages if (item["document_id"], page) not in used]
        if not fresh:
            continue
        if selected and selected_pages + len(fresh) > TARGET_PAGES + 5:
            continue
        selected.append({**item, "pages": pages})
        used.update((item["document_id"], page) for page in pages)
        selected_pages += len(fresh)
        if selected_pages >= TARGET_PAGES:
            break

    return {
        "schema_version": 1,
        "source_structure_schema_version": payload.get("schema_version"),
        "census_generation": payload.get("census_generation"),
        "model": payload.get("model"),
        "policy": {
            "minimum_confidence": MIN_SCORE,
            "maximum_span_pages": MAX_SPAN_PAGES,
            "target_pilot_pages": TARGET_PAGES,
            "rule": "deterministic triangulation; JEV is evidence, never the oracle",
        },
        "counts": {
            "accepted_candidates": len(accepted),
            "rejected_candidates": len(rejected),
            "selected_decisions": len(selected),
            "selected_unique_pages": selected_pages,
        },
        "selected_pilot_decisions": selected,
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
    }


def main() -> int:
    if TARGET_PAGES < 1 or MAX_SPAN_PAGES < 1 or not 0 <= MIN_SCORE <= 1:
        raise ValueError("invalid JEV refinement policy")
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    result = refine(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    if result["counts"]["accepted_candidates"] == 0:
        raise RuntimeError("refinement produced no evidence-backed candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
