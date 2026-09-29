from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any


def _repository_root() -> Path:
    configured = os.getenv("JURISNEXO_REPO_ROOT")
    if configured:
        root = Path(configured)
        if (root / "benchmark/normalization/refine_jev_decision_candidates.py").is_file():
            return root
    for parent in Path(__file__).resolve().parents:
        if (parent / "benchmark/normalization/refine_jev_decision_candidates.py").is_file():
            return parent
    raise AssertionError("could not locate repository root for JEV refinement tests")


def _load() -> ModuleType:
    path = _repository_root() / "benchmark/normalization/refine_jev_decision_candidates.py"
    spec = importlib.util.spec_from_file_location("refine_jev_decision_candidates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(title: str = "Sentencia del 14 de junio de 2006") -> dict[str, Any]:
    return {
        "title": title,
        "candidate_pdf_start": 104,
        "candidate_pdf_end": 109,
        "start_jev": {"judgment": 0.99, "decision_start": 0.93},
        "end_jev": {"judgment": 0.92, "decision_end": 0.88},
        "start_fidelity": "aligned",
        "end_fidelity": "aligned",
    }


def test_editorial_heading_is_negative_evidence_not_hard_truth() -> None:
    module = _load()
    score, _, problems = module._score(_candidate("1.3. Cámaras Reunidas"))
    assert score > 0.0
    assert "editorial_title_signal" in problems
    assert not module._fatal(problems)


def test_rejects_impossible_reverse_span() -> None:
    module = _load()
    candidate = _candidate()
    candidate["candidate_pdf_end"] = 103
    score, _, problems = module._score(candidate)
    assert score == 0.0
    assert problems == ["fatal_non_positive_span"]
    assert module._fatal(problems)


def test_accepts_triangulated_decision_span() -> None:
    module = _load()
    score, reasons, problems = module._score(_candidate())
    assert score >= module.MIN_SCORE
    assert not problems
    assert "jev_strong_start_boundary" in reasons
    assert "verified_start_text" in reasons


def test_weak_boundary_becomes_review_signal_not_format_rejection() -> None:
    module = _load()
    candidate = _candidate("Decisión sin fórmula histórica conocida")
    start_jev = candidate["start_jev"]
    assert isinstance(start_jev, dict)
    start_jev["decision_start"] = 0.10
    score, _, problems = module._score(candidate)
    assert "weak_start_boundary" in problems
    assert not module._fatal(problems)
    assert score >= 0.0


def test_long_decision_is_not_hard_rejected() -> None:
    module = _load()
    candidate = _candidate()
    candidate["candidate_pdf_end"] = 160
    score, _, problems = module._score(candidate)
    assert score > 0.0
    assert "unusual_long_span" in problems
    assert not module._fatal(problems)


def test_ablation_can_disable_format_specific_title_signal() -> None:
    module = _load()
    candidate = _candidate("1.3. Cámaras Reunidas")
    baseline, _, _ = module._score(candidate)
    without_title, _, _ = module._score(candidate, disabled_signals=frozenset({"title"}))
    assert without_title > baseline
