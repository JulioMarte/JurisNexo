from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[2]/"scripts"/"scj_principales_visual_smoke.py"
spec=importlib.util.spec_from_file_location("visual_benchmark",SCRIPT); assert spec and spec.loader
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def test_extract_identifier_ignores_visible_prefix():
    assert m.extract_identifier("NÚM. SCJ-SS-22-0514") == "SCJ-SS-22-0514"
    assert m.extract_identifier("ÚM. SCJ-SS-22-0514\n") == "SCJ-SS-22-0514"

def test_extract_identifier_rejects_missing_identifier():
    assert m.extract_identifier("NÚM. 123") is None

def test_deterministic_selection(monkeypatch):
    cases=[m.Case(f"{i}.pdf",i,f"SCJ-AA-22-{i:04d}","test") for i in range(5)]
    monkeypatch.setattr(m,"SAMPLE_SIZE",2); monkeypatch.setattr(m,"SELECTION","deterministic")
    assert m.select_cases(cases)==cases[:2]

def test_random_selection_is_seeded(monkeypatch):
    cases=[m.Case(f"{i}.pdf",i,f"SCJ-AA-22-{i:04d}","test") for i in range(10)]
    monkeypatch.setattr(m,"SAMPLE_SIZE",4); monkeypatch.setattr(m,"SELECTION","random"); monkeypatch.setattr(m,"SEED",7)
    assert m.select_cases(cases)==m.select_cases(cases)

def test_selection_refuses_oversampling(monkeypatch):
    monkeypatch.setattr(m,"SAMPLE_SIZE",2); monkeypatch.setattr(m,"SELECTION","deterministic")
    try: m.select_cases([m.Case("a.pdf",0,"SCJ-AA-22-0001","test")])
    except ValueError as exc: assert "only 1" in str(exc)
    else: raise AssertionError("expected ValueError")
