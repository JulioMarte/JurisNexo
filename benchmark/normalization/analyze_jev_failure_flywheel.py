"""Mine JEV/deterministic disagreements without letting JEV grade itself.

This tool is diagnostic. It proposes deterministic experiments only when a repeated
failure pattern spans independent documents and source families. JEV is evidence, not
ground truth, and this script never mutates production rules automatically.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

INPUT = Path(
    os.environ.get(
        "JEV_EXCEPTION_OUTPUT",
        ".artifacts/jev-exception-second-pass.json",
    )
)
OUTPUT = Path(
    os.environ.get(
        "JEV_FLYWHEEL_OUTPUT",
        ".artifacts/jev-failure-flywheel.json",
    )
)
MIN_JEV_PROBABILITY = float(
    os.environ.get("JEV_FLYWHEEL_MIN_PROBABILITY", "0.70")
)
MIN_CLUSTER_CASES = int(os.environ.get("JEV_FLYWHEEL_MIN_CLUSTER_CASES", "2"))
MIN_CLUSTER_DOCUMENTS = int(
    os.environ.get("JEV_FLYWHEEL_MIN_CLUSTER_DOCUMENTS", "2")
)
MIN_CLUSTER_FAMILIES = int(
    os.environ.get("JEV_FLYWHEEL_MIN_CLUSTER_FAMILIES", "2")
)

YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
STRUCTURAL_SIGNALS = {
    "decision_opening": ("vist[oa]s?", "considerando", "resulta", "atendido"),
    "decision_closing": (
        "por tales motivos",
        "falla",
        "decide",
        "firmad[oa]",
    ),
}


def _era(year: int | None) -> str:
    if year is None:
        return "year-unknown"
    eras = (
        (1994, 1999),
        (2000, 2005),
        (2006, 2011),
        (2012, 2017),
        (2018, 2022),
        (2023, 2029),
    )
    for start, end in eras:
        if start <= year <= end:
            return f"{start}-{end}"
    return "outside-primary-era"


def _family(item: dict[str, Any]) -> str:
    """Return a conservative family label; explicit upstream metadata wins."""
    explicit = item.get("source_family")
    if explicit:
        return str(explicit)

    haystack = " ".join(
        str(item.get(key) or "") for key in ("object_key", "title")
    )
    match = YEAR.search(haystack)
    year = int(match.group(1)) if match else None

    fidelities = []
    for page in (item.get("expanded_evidence") or {}).values():
        if isinstance(page, dict) and page.get("fidelity"):
            fidelities.append(str(page["fidelity"]))
    unique = set(fidelities)
    if len(unique) > 1:
        fidelity = "mixed-fidelity"
    elif fidelities:
        fidelity = fidelities[0]
    else:
        fidelity = "fidelity-unknown"
    return f"era:{_era(year)}|fidelity:{fidelity}"


def _cluster_key(item: dict[str, Any]) -> str:
    problems = {str(value) for value in item.get("first_pass_problems") or []}
    positives = {
        str(value) for value in item.get("first_pass_positive_evidence") or []
    }
    if "editorial_title_signal" in problems:
        return "title_or_editorial_heuristic"
    if {"weak_start_boundary", "weak_end_boundary"} & problems:
        return "boundary_threshold_or_context"
    if not {"verified_start_text", "verified_end_text"} <= positives:
        return "text_fidelity_or_coverage"
    if not problems:
        return "score_threshold_or_missing_positive_signal"
    return "other_deterministic_signal"


def _structural_features(item: dict[str, Any]) -> list[str]:
    evidence = item.get("expanded_evidence") or {}
    excerpts = (
        str(page.get("excerpt") or "")
        for page in evidence.values()
        if isinstance(page, dict)
    )
    text = " ".join(excerpts).lower()
    found = []
    for name, patterns in STRUCTURAL_SIGNALS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            found.append(name)
    return found


def _proposal(cluster: str, shared_features: list[str]) -> dict[str, Any]:
    mapping = {
        "title_or_editorial_heuristic": (
            "A title/editorial convention may suppress real decisions.",
            "Ablate title evidence; compare precision/recall on a frozen "
            "source-family holdout.",
        ),
        "boundary_threshold_or_context": (
            "Fixed boundary thresholds or context width may reject valid spans.",
            "Sweep thresholds and 2-page versus 4-page context on discovery "
            "families, then evaluate once on holdout.",
        ),
        "text_fidelity_or_coverage": (
            "Missing or unaligned text may lower valid candidates.",
            "Compare native text, independent OCR and visual evidence before "
            "changing scoring weights.",
        ),
        "score_threshold_or_missing_positive_signal": (
            "The scorer may lack a positive structural signal.",
            "Test one cheap structural signal at a time and require holdout "
            "improvement without precision regression.",
        ),
        "other_deterministic_signal": (
            "A less common deterministic signal may cause systematic false negatives.",
            "Run one-signal-at-a-time ablations and preserve exact exception traces.",
        ),
    }
    hypothesis, experiment = mapping[cluster]
    if shared_features:
        experiment += " Candidate distilled signals: " + ", ".join(shared_features) + "."
    return {"hypothesis": hypothesis, "next_experiment": experiment}


def _validated_probability(second: dict[str, Any]) -> float | None:
    try:
        probability = float(second.get("span_verdict_probability"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= probability <= 1.0:
        return None
    return probability


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    exceptions = payload.get("exceptions") or []
    if not isinstance(exceptions, list):
        raise ValueError("exceptions must be a list")

    disagreements: list[dict[str, Any]] = []
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected_reasons: Counter[str] = Counter()

    for item in exceptions:
        if not isinstance(item, dict):
            rejected_reasons["malformed_exception"] += 1
            continue
        second = item.get("second_pass") or {}
        probability = _validated_probability(second)
        if probability is None:
            rejected_reasons["invalid_probability"] += 1
            continue
        if second.get("span_verdict") != "supported":
            rejected_reasons["not_supported"] += 1
            continue
        if probability < MIN_JEV_PROBABILITY:
            rejected_reasons["below_probability_threshold"] += 1
            continue

        required = (
            "exception_id",
            "document_id",
            "object_key",
            "candidate_pdf_start",
            "first_pass_score",
        )
        if any(key not in item for key in required):
            rejected_reasons["missing_required_evidence"] += 1
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
            "first_pass_positive_evidence": (
                item.get("first_pass_positive_evidence") or []
            ),
            "jev_supported_probability": probability,
            "jev_failure_mode": second.get("failure_mode"),
            "expanded_evidence_sha256": item.get("expanded_evidence_sha256"),
            "source_family": _family(item),
            "distillable_structural_features": _structural_features(item),
        }
        row["diagnostic_cluster"] = _cluster_key(item)
        disagreements.append(row)
        clusters[row["diagnostic_cluster"]].append(row)

    proposals = []
    quarantined = []
    ordered_clusters = sorted(
        clusters.items(),
        key=lambda pair: (-len(pair[1]), pair[0]),
    )
    for cluster, rows in ordered_clusters:
        documents = sorted({str(row["document_id"]) for row in rows})
        families = sorted({str(row["source_family"]) for row in rows})
        feature_counts = Counter(
            feature
            for row in rows
            for feature in row["distillable_structural_features"]
        )
        shared_features = sorted(
            feature
            for feature, count in feature_counts.items()
            if count >= max(2, len(rows) // 2)
        )
        candidate = {
            "cluster": cluster,
            "case_count": len(rows),
            "exception_ids": [row["exception_id"] for row in rows],
            "documents": documents,
            "source_families": families,
            "mean_jev_support": round(
                sum(row["jev_supported_probability"] for row in rows) / len(rows),
                4,
            ),
            "observed_problem_counts": dict(
                Counter(
                    problem
                    for row in rows
                    for problem in row["first_pass_problems"]
                )
            ),
            "shared_distillable_features": shared_features,
            **_proposal(cluster, shared_features),
            "automatic_code_change_allowed": False,
            "required_validation": (
                "freeze discovery families; evaluate exactly once on a disjoint "
                "source-family holdout; require regression suite and preserved "
                "evidence packet"
            ),
        }
        blockers = []
        if len(rows) < MIN_CLUSTER_CASES:
            blockers.append("insufficient_cases")
        if len(documents) < MIN_CLUSTER_DOCUMENTS:
            blockers.append("insufficient_independent_documents")
        if len(families) < MIN_CLUSTER_FAMILIES:
            blockers.append("insufficient_source_family_diversity")
        candidate["promotion_blockers"] = blockers
        target = quarantined if blockers else proposals
        target.append(candidate)

    return {
        "schema_version": 3,
        "purpose": (
            "mine reproducible disagreements into deterministic hypotheses with "
            "leakage-resistant family holdouts"
        ),
        "policy": {
            "minimum_jev_supported_probability": MIN_JEV_PROBABILITY,
            "minimum_cluster_cases": MIN_CLUSTER_CASES,
            "minimum_cluster_documents": MIN_CLUSTER_DOCUMENTS,
            "minimum_cluster_source_families": MIN_CLUSTER_FAMILIES,
            "jev_is_ground_truth": False,
            "automatic_regex_generation": False,
            "automatic_parser_mutation": False,
            "promotion_requires_held_out_validation": True,
            "random_page_split_is_valid_holdout": False,
            "holdout_unit": "source_family",
            "holdout_must_be_frozen_before_rule_change": True,
            "fallback_family_is_provisional": True,
        },
        "counts": {
            "exceptions_seen": len(exceptions),
            "high_confidence_disagreements": len(disagreements),
            "proposal_clusters": len(proposals),
            "quarantined_clusters": len(quarantined),
            "rejected_exceptions": sum(rejected_reasons.values()),
        },
        "rejected_reason_counts": dict(rejected_reasons),
        "disagreements": disagreements,
        "improvement_proposals": proposals,
        "quarantined_hypotheses": quarantined,
    }


def main() -> int:
    if not 0 <= MIN_JEV_PROBABILITY <= 1:
        raise ValueError("invalid JEV probability threshold")
    minimums = (
        MIN_CLUSTER_CASES,
        MIN_CLUSTER_DOCUMENTS,
        MIN_CLUSTER_FAMILIES,
    )
    if min(minimums) < 1:
        raise ValueError("invalid flywheel cluster policy")

    result = analyze(json.loads(INPUT.read_text(encoding="utf-8")))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    OUTPUT.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
