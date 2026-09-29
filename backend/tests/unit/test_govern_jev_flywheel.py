from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any


def _repo_root() -> Path:
    configured = os.environ.get("JURISNEXO_REPO_ROOT")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        if (parent / "benchmark" / "normalization").is_dir():
            return parent
    raise RuntimeError("unable to locate repository root")


def _load() -> ModuleType:
    path = _repo_root() / "benchmark" / "normalization" / "govern_jev_flywheel.py"
    spec = importlib.util.spec_from_file_location("govern_jev_flywheel", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(families: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "counts": {"proposal_clusters": 1, "quarantined_clusters": 0},
        "policy": {"automatic_parser_mutation": False},
        "improvement_proposals": [
            {
                "cluster": "boundary_threshold_or_context",
                "source_families": families,
                "promotion_blockers": [],
            }
        ],
        "quarantined_hypotheses": [],
    }


def test_same_era_fidelity_variants_are_not_independent() -> None:
    module = _load()
    result = module.govern(
        _payload(
            [
                "era:2006-2011|fidelity:aligned",
                "era:2006-2011|fidelity:misaligned",
                "era:2006-2011|fidelity:mixed-fidelity",
            ]
        )
    )
    assert result["improvement_proposals"] == []
    candidate = result["quarantined_hypotheses"][0]
    assert candidate["generalization_groups"] == ["era:2006-2011"]
    assert "insufficient_cross_era_or_explicit_family_diversity" in candidate["promotion_blockers"]


def test_cross_era_candidate_remains_eligible_for_holdout_not_auto_promotion() -> None:
    module = _load()
    result = module.govern(
        _payload(
            [
                "era:2000-2005|fidelity:aligned",
                "era:2012-2017|fidelity:aligned",
            ]
        )
    )
    assert len(result["improvement_proposals"]) == 1
    candidate = result["improvement_proposals"][0]
    assert candidate["promotion_blockers"] == []
    assert result["policy"]["promotion_requires_held_out_validation"] is True
    assert result["policy"]["automatic_parser_mutation"] is False


def test_explicit_upstream_families_can_supply_independence() -> None:
    module = _load()
    result = module.govern(_payload(["scj-bulletin", "tc-resolution"]))
    assert len(result["improvement_proposals"]) == 1
    policy = result["policy"]
    assert policy["fidelity_variants_count_as_independent_generalization"] is False
