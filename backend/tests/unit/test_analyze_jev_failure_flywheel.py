from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType


def _repo_root() -> Path:
    configured = os.environ.get("JURISNEXO_REPO_ROOT")
    if configured:
        root = Path(configured)
        if (root / "benchmark" / "normalization").is_dir():
            return root

    for parent in Path(__file__).resolve().parents:
        if (parent / "benchmark" / "normalization").is_dir():
            return parent
    raise RuntimeError("unable to locate JurisNexo repository root")


def _load() -> ModuleType:
    path = (
        _repo_root()
        / "benchmark"
        / "normalization"
        / "analyze_jev_failure_flywheel.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_jev_failure_flywheel", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(
    number: int,
    *,
    problem: str,
    probability: float = 0.9,
    family: str | None = None,
) -> dict:
    item = {
        "exception_id": f"exception-{number:04d}",
        "document_id": f"doc-{number}",
        "object_key": f"source-{2000 + number}.pdf",
        "title": "Sentencia",
        "candidate_pdf_start": 10,
        "candidate_pdf_end": 12,
        "first_pass_score": 0.4,
        "first_pass_problems": [problem],
        "first_pass_positive_evidence": [
            "verified_start_text",
            "verified_end_text",
        ],
        "expanded_evidence_sha256": f"sha-{number}",
        "expanded_evidence": {
            "start": {
                "fidelity": "aligned",
                "excerpt": "Vistos. Considerando los hechos.",
            },
            "end": {
                "fidelity": "aligned",
                "excerpt": "Por tales motivos, falla.",
            },
        },
        "second_pass": {
            "span_verdict": "supported",
            "span_verdict_probability": probability,
            "failure_mode": "none",
        },
    }
    if family:
        item["source_family"] = family
    return item


def test_requires_independent_source_families_and_never_auto_mutates() -> None:
    module = _load()
    payload = {
        "exceptions": [
            _case(1, problem="editorial_title_signal", family="era-a"),
            _case(2, problem="editorial_title_signal", family="era-b"),
        ]
    }
    result = module.analyze(payload)
    assert result["counts"]["proposal_clusters"] == 1
    proposal = result["improvement_proposals"][0]
    assert proposal["promotion_blockers"] == []
    assert proposal["source_families"] == ["era-a", "era-b"]
    assert "decision_opening" in proposal["shared_distillable_features"]
    assert "decision_closing" in proposal["shared_distillable_features"]
    assert proposal["automatic_code_change_allowed"] is False
    assert result["policy"]["jev_is_ground_truth"] is False
    assert result["policy"]["random_page_split_is_valid_holdout"] is False
    assert result["policy"]["holdout_must_be_frozen_before_rule_change"] is True


def test_same_family_cluster_is_quarantined_not_promoted() -> None:
    module = _load()
    result = module.analyze(
        {
            "exceptions": [
                _case(1, problem="editorial_title_signal", family="same"),
                _case(2, problem="editorial_title_signal", family="same"),
            ]
        }
    )
    assert result["improvement_proposals"] == []
    assert result["counts"]["quarantined_clusters"] == 1
    blockers = result["quarantined_hypotheses"][0]["promotion_blockers"]
    assert "insufficient_source_family_diversity" in blockers


def test_ignores_low_confidence_or_contradicted_model_opinions() -> None:
    module = _load()
    low = _case(1, problem="weak_start_boundary", probability=0.55, family="a")
    contradicted = _case(2, problem="weak_start_boundary", family="b")
    contradicted["second_pass"]["span_verdict"] = "contradicted"
    result = module.analyze({"exceptions": [low, contradicted]})
    assert result["counts"]["high_confidence_disagreements"] == 0
    assert result["improvement_proposals"] == []
