"""Apply a stricter, cross-era promotion gate to JEV flywheel hypotheses.

The diagnostic miner may use fidelity as part of a provisional source-family label.
That is useful for analysis, but aligned/misaligned variants from the same editorial
era are not independent evidence of generalization. This pass therefore requires a
candidate to span multiple editorial eras (or multiple explicit upstream families)
before it can remain promotion-eligible. It never changes parser code.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

INPUT = Path(os.environ.get("JEV_FLYWHEEL_OUTPUT", ".artifacts/jev-failure-flywheel.json"))
OUTPUT = Path(os.environ.get("JEV_GOVERNED_FLYWHEEL_OUTPUT", ".artifacts/jev-failure-flywheel-governed.json"))
MIN_GENERALIZATION_GROUPS = int(os.environ.get("JEV_FLYWHEEL_MIN_GENERALIZATION_GROUPS", "2"))

ERA = re.compile(r"(?:^|\|)era:([^|]+)")


def _generalization_group(family: str) -> str:
    """Collapse fidelity variants of the same era into one independence group."""
    match = ERA.search(family)
    if match:
        return f"era:{match.group(1)}"
    # Explicit upstream families remain distinct. They are expected to encode a
    # real provenance/editorial distinction rather than page-level fidelity.
    return f"explicit:{family}"


def govern(payload: dict[str, Any]) -> dict[str, Any]:
    proposals = payload.get("improvement_proposals") or []
    quarantined = list(payload.get("quarantined_hypotheses") or [])
    eligible: list[dict[str, Any]] = []

    for raw in proposals:
        candidate = dict(raw)
        families = [str(value) for value in candidate.get("source_families") or []]
        groups = sorted({_generalization_group(value) for value in families})
        candidate["generalization_groups"] = groups
        candidate["minimum_generalization_groups"] = MIN_GENERALIZATION_GROUPS
        blockers = list(candidate.get("promotion_blockers") or [])
        if len(groups) < MIN_GENERALIZATION_GROUPS:
            blockers.append("insufficient_cross_era_or_explicit_family_diversity")
        candidate["promotion_blockers"] = sorted(set(blockers))
        if blockers:
            quarantined.append(candidate)
        else:
            eligible.append(candidate)

    result = dict(payload)
    result["schema_version"] = max(int(payload.get("schema_version") or 0), 4)
    result["improvement_proposals"] = eligible
    result["quarantined_hypotheses"] = quarantined
    counts = dict(payload.get("counts") or {})
    counts["proposal_clusters"] = len(eligible)
    counts["quarantined_clusters"] = len(quarantined)
    result["counts"] = counts
    policy = dict(payload.get("policy") or {})
    policy.update(
        {
            "minimum_generalization_groups": MIN_GENERALIZATION_GROUPS,
            "fidelity_variants_count_as_independent_generalization": False,
            "cross_era_or_explicit_family_diversity_required": True,
            "automatic_parser_mutation": False,
            "promotion_requires_held_out_validation": True,
        }
    )
    result["policy"] = policy
    return result


def main() -> int:
    if MIN_GENERALIZATION_GROUPS < 2:
        raise ValueError("JEV_FLYWHEEL_MIN_GENERALIZATION_GROUPS must be >= 2")
    result = govern(json.loads(INPUT.read_text(encoding="utf-8")))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
