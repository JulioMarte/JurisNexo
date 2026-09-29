"""Turn JEV/deterministic disagreements into auditable improvement hypotheses.

This is deliberately a *proposal* generator, not a self-modifying regex engine. A model
opinion can reveal where deterministic evidence is brittle, but it must not rewrite the
parser or become its own ground truth. Every proposal keeps the source exception ids,
observed first-pass signals and second-pass probabilities so an agent or human can
inspect the evidence before changing code.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

INPUT = Path(os.environ.get("JEV_EXCEPTION_OUTPUT", ".artifacts/jev-exception-second-pass.json"))
OUTPUT = Path(os.environ.get("JEV_FLYWHEEL_OUTPUT", ".artifacts/jev-failure-flywheel.json"))
MIN_JEV_PROBABILITY = float(os.environ.get("JEV_FLYWHEEL_MIN_PROBABILITY", "0.70"))
MIN_CLUSTER_CASES = int(os.environ.get("JEV_FLYWHEEL_MIN_CLUSTER_CASES", "2"))


def _cluster_key(item: dict[str, Any]) -> str:
    problems = tuple(sorted(str(x) for x in item.get("first_pass_problems") or []))
    positives = tuple(sorted(str(x) for x in item.get("first_pass_positive_evidence") or []))
    if "editorial_title_signal" in problems:
        return "title_or_editorial_heuristic"
    if "weak_start_boundary" in problems or "weak_end_boundary" in problems:
        return "boundary_threshold_or_context"
    if "verified_start_text" not in positives or "verified_end_text" not in positives:
        return "text_fidelity_or_coverage"
    if not problems:
        return "score_threshold_or_missing_positive_signal"
    return "other_deterministic_signal"


def _proposal(cluster: str) -> dict[str, str]:
    mapping = {
        "title_or_editorial_heuristic": {
            "hypothesis": "A title/editorial convention may be suppressing real decisions in some format families.",
            "next_experiment": "Stratify by decade/source layout; ablate title evidence and compare boundary precision/recall on held-out families.",
        },
        "boundary_threshold_or_context": {
            "hypothesis": "Fixed JEV boundary thresholds or too little neighboring context may reject valid spans.",
            "next_experiment": "Sweep boundary thresholds on source-separated holdouts and compare 2-page versus 4-page neighbor context.",
        },
        "text_fidelity_or_coverage": {
            "hypothesis": "Missing/unaligned text evidence may be lowering otherwise valid candidates.",
            "next_experiment": "Compare native text, independent OCR and visual evidence for these exact pages before changing scoring weights.",
        },
        "score_threshold_or_missing_positive_signal": {
            "hypothesis": "The deterministic scorer may lack a positive signal present in valid decisions.",
            "next_experiment": "Inspect shared trace features, propose one explicit signal, then test it on a frozen family holdout before adoption.",
        },
        "other_deterministic_signal": {
            "hypothesis": "A less common deterministic signal may be causing systematic false negatives.",
            "next_experiment": "Inspect the attached exception traces and run a one-signal-at-a-time ablation before changing code.",
        },
    }
    return mapping[cluster]


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    disagreements: list[dict[str, Any]] = []
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload.get("exceptions", []):
        second = item.get("second_pass") or {}
        if second.get("span_verdict") != "supported":
            continue
        probability = float(second.get("span_verdict_probability") or 0.0)
        if probability < MIN_JEV_PROBABILITY:
            continue
        row = {
            "exception_id": item["exception_id"],
            "document_id": item["document_id"],
            "object_key": item["object_key"],
            "title": item.get("title"),
            "candidate_pdf_start": item["candidate_pdf_start"],
            "candidate_pdf_end": item.get("candidate_pdf_end"),
            "first_pass_score": item["first_pass_score"],
            "first_pass_problems": item.get("first_pass_problems") or [],
            "first_pass_positive_evidence": item.get("first_pass_positive_evidence") or [],
            "jev_supported_probability": probability,
            "jev_failure_mode": second.get("failure_mode"),
            "expanded_evidence_sha256": item.get("expanded_evidence_sha256"),
        }
        cluster = _cluster_key(item)
        row["diagnostic_cluster"] = cluster
        disagreements.append(row)
        clusters[cluster].append(row)

    proposals: list[dict[str, Any]] = []
    for cluster, rows in sorted(clusters.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        if len(rows) < MIN_CLUSTER_CASES:
            continue
        proposal = _proposal(cluster)
        proposals.append({
            "cluster": cluster,
            "case_count": len(rows),
            "exception_ids": [row["exception_id"] for row in rows],
            "documents": sorted({row["document_id"] for row in rows}),
            "mean_jev_support": round(sum(row["jev_supported_probability"] for row in rows) / len(rows), 4),
            "observed_problem_counts": dict(Counter(problem for row in rows for problem in row["first_pass_problems"])),
            **proposal,
            "automatic_code_change_allowed": False,
            "required_validation": "source-family holdout + regression suite + preserved evidence packet",
        })

    return {
        "schema_version": 1,
        "purpose": "mine reproducible JEV-vs-deterministic disagreements into testable hypotheses",
        "policy": {
            "minimum_jev_supported_probability": MIN_JEV_PROBABILITY,
            "minimum_cluster_cases": MIN_CLUSTER_CASES,
            "jev_is_ground_truth": False,
            "automatic_regex_generation": False,
            "automatic_parser_mutation": False,
            "promotion_requires_held_out_validation": True,
        },
        "counts": {
            "exceptions_seen": len(payload.get("exceptions", [])),
            "high_confidence_disagreements": len(disagreements),
            "proposal_clusters": len(proposals),
        },
        "disagreements": disagreements,
        "improvement_proposals": proposals,
    }


def main() -> int:
    if not 0.0 <= MIN_JEV_PROBABILITY <= 1.0 or MIN_CLUSTER_CASES < 1:
        raise ValueError("invalid flywheel policy")
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    result = analyze(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
