"""Measure how format-specific heuristics change JEV structural candidate dispositions.

This is diagnostic, not a promotion gate. It makes hidden dependence on titles, span
length, text fidelity, or JEV boundary scores visible before those assumptions become
production policy.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from refine_jev_decision_candidates import MIN_SCORE, REVIEW_SCORE, _fatal, _score

INPUT = Path(os.environ.get("JEV_STRUCTURE_OUTPUT", ".artifacts/jev-structure-pilot.json"))
OUTPUT = Path(os.environ.get("JEV_ABLATION_OUTPUT", ".artifacts/jev-structure-ablations.json"))

PROFILES: dict[str, frozenset[str]] = {
    "all_signals": frozenset(),
    "no_title_format": frozenset({"title"}),
    "no_span_length": frozenset({"span_length"}),
    "no_fidelity": frozenset({"fidelity"}),
    "jev_only": frozenset({"title", "span_length", "fidelity"}),
    "non_jev_only": frozenset({"jev_boundary"}),
}


def _disposition(score: float, problems: list[str]) -> str:
    if _fatal(problems):
        return "impossible"
    if score >= MIN_SCORE:
        return "strong"
    if score >= REVIEW_SCORE:
        return "review"
    return "weak"


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for document in payload["documents"]:
        for index, candidate in enumerate(document["decision_candidates"]):
            row: dict[str, Any] = {"document_id": document["document_id"], "candidate_index": index, "title": candidate.get("title"), "candidate_pdf_start": candidate.get("candidate_pdf_start"), "candidate_pdf_end": candidate.get("candidate_pdf_end"), "profiles": {}}
            for name, disabled in PROFILES.items():
                score, reasons, problems = _score(candidate, disabled_signals=disabled)
                row["profiles"][name] = {"score": round(score, 4), "disposition": _disposition(score, problems), "positive_evidence": reasons, "warnings": problems}
            candidates.append(row)

    summaries: dict[str, Any] = {}
    baseline = "all_signals"
    for name in PROFILES:
        dispositions = Counter(row["profiles"][name]["disposition"] for row in candidates)
        changed = sum(row["profiles"][name]["disposition"] != row["profiles"][baseline]["disposition"] for row in candidates)
        summaries[name] = {"dispositions": dict(sorted(dispositions.items())), "changed_vs_all_signals": changed}

    return {"schema_version": 1, "purpose": "ablation study: expose dependence on historical-format heuristics", "candidate_count": len(candidates), "profiles": {name: sorted(disabled) for name, disabled in PROFILES.items()}, "summary": summaries, "candidates": candidates, "interpretation_rule": "A heuristic that changes many dispositions must be validated across eras/formats before becoming policy; this report does not establish semantic gold."}


def main() -> int:
    result = evaluate(json.loads(INPUT.read_text(encoding="utf-8")))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
