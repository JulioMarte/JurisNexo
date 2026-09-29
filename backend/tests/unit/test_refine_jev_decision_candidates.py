from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load() -> ModuleType:
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "benchmark" / "normalization" / "refine_jev_decision_candidates.py").is_file()
    )
    path = root / "benchmark" / "normalization" / "refine_jev_decision_candidates.py"
    spec = importlib.util.spec_from_file_location("refine_jev_decision_candidates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _candidate(title: str = "Sentencia del 14 de junio de 2006") -> dict:
    return {
        "title": title,
        "candidate_pdf_start": 104,
        "candidate_pdf_end": 109,
        "start_jev": {"judgment": 0.99, "decision_start": 0.93},
        "end_jev": {"judgment": 0.92, "decision_end": 0.88},
        "start_fidelity": "aligned",
        "end_fidelity": "aligned",
    }


def test_rejects_editorial_heading_even_with_strong_jev_scores() -> None:
    module = _load()
    score, _, problems = module._score(_candidate("1.3. Cámaras Reunidas"))
    assert score == 0.0
    assert problems == ["editorial_index_heading"]


def test_rejects_impossible_reverse_span() -> None:
    module = _load()
    candidate = _candidate()
    candidate["candidate_pdf_end"] = 103
    score, _, problems = module._score(candidate)
    assert score == 0.0
    assert problems == ["non_positive_span"]


def test_accepts_triangulated_decision_span() -> None:
    module = _load()
    score, reasons, problems = module._score(_candidate())
    assert score >= module.MIN_SCORE
    assert not problems
    assert "jev_strong_start_boundary" in reasons
    assert "verified_start_text" in reasons


def test_weak_boundary_is_not_promoted() -> None:
    module = _load()
    candidate = _candidate()
    candidate["start_jev"]["decision_start"] = 0.10
    score, _, problems = module._score(candidate)
    assert score < module.MIN_SCORE or problems
    assert "weak_start_boundary" in problems
