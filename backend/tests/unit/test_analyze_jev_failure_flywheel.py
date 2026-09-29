from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load() -> ModuleType:
    path = Path(__file__).parents[3] / "benchmark" / "normalization" / "analyze_jev_failure_flywheel.py"
    spec = importlib.util.spec_from_file_location("analyze_jev_failure_flywheel", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(number: int, *, problem: str, probability: float = 0.9) -> dict:
    return {
        "exception_id": f"exception-{number:04d}",
        "document_id": f"doc-{number}",
        "object_key": f"source-{number}.pdf",
        "title": "Sentencia",
        "candidate_pdf_start": 10,
        "candidate_pdf_end": 12,
        "first_pass_score": 0.4,
        "first_pass_problems": [problem],
        "first_pass_positive_evidence": ["verified_start_text", "verified_end_text"],
        "expanded_evidence_sha256": f"sha-{number}",
        "second_pass": {
            "span_verdict": "supported",
            "span_verdict_probability": probability,
            "failure_mode": "none",
        },
    }


def test_clusters_repeat_disagreements_but_never_auto_mutates_code() -> None:
    module = _load()
    payload = {"exceptions": [_case(1, problem="editorial_title_signal"), _case(2, problem="editorial_title_signal")]}
    result = module.analyze(payload)
    assert result["counts"]["high_confidence_disagreements"] == 2
    assert result["counts"]["proposal_clusters"] == 1
    proposal = result["improvement_proposals"][0]
    assert proposal["cluster"] == "title_or_editorial_heuristic"
    assert proposal["automatic_code_change_allowed"] is False
    assert "holdout" in proposal["required_validation"]
    assert result["policy"]["jev_is_ground_truth"] is False
    assert result["policy"]["automatic_regex_generation"] is False


def test_ignores_low_confidence_or_contradicted_model_opinions() -> None:
    module = _load()
    low = _case(1, problem="weak_start_boundary", probability=0.55)
    contradicted = _case(2, problem="weak_start_boundary")
    contradicted["second_pass"]["span_verdict"] = "contradicted"
    result = module.analyze({"exceptions": [low, contradicted]})
    assert result["counts"]["high_confidence_disagreements"] == 0
    assert result["improvement_proposals"] == []
