from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


def _repository_root() -> Path:
    configured = os.getenv("JURISNEXO_REPO_ROOT")
    if configured:
        root = Path(configured)
        if (root / "benchmark" / "normalization" / "jev_structure_pilot.py").is_file():
            return root
    for parent in Path(__file__).resolve().parents:
        if (parent / "benchmark" / "normalization" / "jev_structure_pilot.py").is_file():
            return parent
    raise AssertionError("could not locate repository root from test path")


def _load() -> ModuleType:
    path = _repository_root() / "benchmark" / "normalization" / "jev_structure_pilot.py"
    spec = importlib.util.spec_from_file_location("jev_structure_pilot", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_root_honors_ci_mount(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pilot = tmp_path / "benchmark" / "normalization" / "jev_structure_pilot.py"
    pilot.parent.mkdir(parents=True)
    pilot.write_text("# test fixture\n", encoding="utf-8")
    monkeypatch.setenv("JURISNEXO_REPO_ROOT", str(tmp_path))
    assert _repository_root() == tmp_path


def test_index_entries_extract_editorial_page_reference() -> None:
    module = _load()
    text = (
        "SUMARIO\n"
        "Recurso de casación de Acme, S. A. ........ 183\n"
        "Otra decisión      191\n"
    )
    assert module._index_entries(text, source_page=7) == [
        {
            "raw": "Recurso de casación de Acme, S. A. ........ 183",
            "title": "Recurso de casación de Acme, S. A",
            "printed_start_page": 183,
            "source_index_page": 7,
        },
        {
            "raw": "Otra decisión      191",
            "title": "Otra decisión",
            "printed_start_page": 191,
            "source_index_page": 7,
        },
    ]


def test_dominant_offset_uses_multiple_printed_page_anchors() -> None:
    module = _load()
    texts = {
        10: "cabecera\n1\n",
        11: "cabecera\n2\n",
        12: "cabecera\n3\n",
        20: "cabecera\n999\n",
    }
    offset, anchors = module._dominant_offset(texts)
    assert offset == 10
    assert len(anchors) == 4


def test_candidate_pages_prioritize_index_signals() -> None:
    module = _load()
    texts = {index: "texto ordinario" for index in range(50)}
    texts[35] = "ÍNDICE\nCaso importante ........ 183\nOtro caso ........ 191"
    selected = module._candidate_pages(texts)
    assert 35 in selected
