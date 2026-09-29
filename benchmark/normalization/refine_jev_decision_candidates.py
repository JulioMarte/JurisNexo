"""Refine JEV structural hypotheses into evidence-scored decision candidates.

Only factual impossibilities are hard rejects. Format conventions (titles, span length,
boundary confidence, text fidelity) are evidence signals, not definitions of a judicial
decision. This matters across decades where SCJ formatting changes substantially.
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
REVIEW_SCORE = float(os.environ.get("JEV_REFINED_REVIEW_SCORE", "0.45"))

_DECISION_TITLE = re.compile(r"\b(?:sentencia|resoluci[oó]n|auto|recurso|casaci[oó]n|habeas|amparo)\b", re.IGNORECASE)
_EDITORIAL_TITLE = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s*)?(?:c[aá]maras?\s+reunidas|primera\s+sala|segunda\s+sala|tercera\s+sala|pleno|materia\s+\w+|secci[oó]n|cap[ií]tulo|[ií]ndice|sumario|contenido)\s*$", re.IGNORECASE)


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


def _score(candidate: dict[str, Any], *, disabled_signals: frozenset[str] = frozenset()) -> tuple[float, list[str], list[str]]:
    """Score evidence without treating historical formatting conventions as truth.

    `problems` are warnings unless prefixed ``fatal_``. disabled_signals exists so the
    benchmark can run ablations and measure which heuristics help or hurt recall.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    start = int(candidate["candidate_pdf_start"])
    end_raw = candidate.get("candidate_pdf_end")
    if end_raw is None:
        return 0.0, reasons, ["fatal_open_ended_span"]
    end = int(end_raw)
    span_pages = end - start + 1
    if span_pages <= 0:
        return 0.0, reasons, ["fatal_non_positive_span"]

    score = 0.0
    title_kind = _title_kind(str(candidate.get("title") or ""))
    if "title" not in disabled_signals:
        if title_kind == "decision_like":
            score += 0.18
            reasons.append("decision_like_index_title")
        elif title_kind == "editorial":
            score -= 0.18
            warnings.append("editorial_title_signal")

    start_judgment = _prob(candidate, "start", "judgment")
    start_boundary = _prob(candidate, "start", "decision_start")
    end_boundary = _prob(candidate, "end", "decision_end")
    end_judgment = _prob(candidate, "end", "judgment")
    if "jev_boundary" not in disabled_signals:
        if start_judgment >= 0.80:
            score += 0.18
            reasons.append("jev_start_is_judgment")
        if start_boundary >= 0.70:
            score += 0.22
            reasons.append("jev_strong_start_boundary")
        elif start_boundary < 0.35:
            score -= 0.14
            warnings.append("weak_start_boundary")
        if end_boundary >= 0.65:
            score += 0.18
            reasons.append("jev_strong_end_boundary")
        elif end_boundary < 0.35:
            score -= 0.14
            warnings.append("weak_end_boundary")
        if end_judgment >= 0.60:
            score += 0.08
            reasons.append("jev_end_is_judgment")

    if "fidelity" not in disabled_signals:
        if _fidelity(candidate, "start"):
            score += 0.08
            reasons.append("verified_start_text")
        if _fidelity(candidate, "end"):
            score += 0.06
            reasons.append("verified_end_text")

    if "span_length" not in disabled_signals:
        if 1 <= span_pages <= 25:
            score += 0.02
            reasons.append("common_span_length")
        elif span_pages > MAX_SPAN_PAGES:
            score -= 0.04
            warnings.append("unusual_long_span")

    return max(0.0, min(score, 1.0)), reasons, warnings


def _fatal(problems: list[str]) -> bool:
    return any(problem.startswith("fatal_") for problem in problems)


def refine(payload: dict[str, Any]) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for document in payload["documents"]:
        identity = {"object_key": document["object_key"], "document_id": document["document_id"], "source_pdf_sha256": document["source_pdf_sha256"]}
        for candidate in document["decision_candidates"]:
            score, reasons, problems = _score(candidate)
            item = {**identity, "title": candidate.get("title"), "printed_start_page": candidate.get("printed_start_page"), "source_index_page": candidate.get("source_index_page"), "candidate_pdf_start": candidate.get("candidate_pdf_start"), "candidate_pdf_end": candidate.get("candidate_pdf_end"), "confidence_score": round(score, 4), "positive_evidence": reasons, "problems": problems, "start_jev": candidate.get("start_jev"), "end_jev": candidate.get("end_jev"), "start_fidelity": candidate.get("start_fidelity"), "end_fidelity": candidate.get("end_fidelity")}
            if _fatal(problems):
                item["disposition"] = "rejected_impossible"
                rejected.append(item)
            elif score >= MIN_SCORE:
                item["disposition"] = "accepted_strong_evidence"
                accepted.append(item)
            elif score >= REVIEW_SCORE:
                item["disposition"] = "review_format_uncertain"
                review.append(item)
                rejected.append(item)  # retained for the auditable second pass
            else:
                item["disposition"] = "review_weak_evidence"
                rejected.append(item)

    accepted.sort(key=lambda item: (-float(item["confidence_score"]), item["object_key"], int(item["candidate_pdf_start"])))
    selected: list[dict[str, Any]] = []
    selected_pages = 0
    used: set[tuple[str, int]] = set()
    for item in accepted:
        start, end = int(item["candidate_pdf_start"]), int(item["candidate_pdf_end"])
        pages = list(range(start, end + 1))
        fresh = [page for page in pages if (item["document_id"], page) not in used]
        if not fresh or (selected and selected_pages + len(fresh) > TARGET_PAGES + 5):
            continue
        selected.append({**item, "pages": pages})
        used.update((item["document_id"], page) for page in pages)
        selected_pages += len(fresh)
        if selected_pages >= TARGET_PAGES:
            break

    return {"schema_version": 2, "source_structure_schema_version": payload.get("schema_version"), "census_generation": payload.get("census_generation"), "model": payload.get("model"), "policy": {"minimum_confidence": MIN_SCORE, "review_confidence": REVIEW_SCORE, "maximum_span_pages": MAX_SPAN_PAGES, "target_pilot_pages": TARGET_PAGES, "rule": "format conventions are evidence, never hard truth; only factual impossibilities are hard rejects"}, "counts": {"accepted_candidates": len(accepted), "review_candidates": len(review), "rejected_candidates": len(rejected), "selected_decisions": len(selected), "selected_unique_pages": selected_pages}, "selected_pilot_decisions": selected, "accepted_candidates": accepted, "review_candidates": review, "rejected_candidates": rejected}


def main() -> int:
    if TARGET_PAGES < 1 or MAX_SPAN_PAGES < 1 or not 0 <= REVIEW_SCORE <= MIN_SCORE <= 1:
        raise ValueError("invalid JEV refinement policy")
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    result = refine(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    if result["counts"]["accepted_candidates"] == 0:
        raise RuntimeError("refinement produced no strong evidence candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
