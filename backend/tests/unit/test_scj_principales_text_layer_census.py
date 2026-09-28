from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "scj_principales_text_layer_census.py"
    )
    spec = importlib.util.spec_from_file_location("scj_text_layer_census", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classifies_low_information_and_missing_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def empty_ocr(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(text="", mean_confidence=99.0)

    monkeypatch.setattr(module, "run_tesseract_visual_ocr", empty_ocr)
    assert (
        module.classify_page(native_text="", image=b"png")["classification"]
        == "low_information"
    )

    visible = "palabra " * 100

    def visible_ocr(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(text=visible, mean_confidence=99.0)

    monkeypatch.setattr(module, "run_tesseract_visual_ocr", visible_ocr)
    assert (
        module.classify_page(native_text="", image=b"png")["classification"]
        == "no_native_text"
    )


def test_aggregate_counts_normalization_need(tmp_path: Path) -> None:
    module = _module()
    shards = tmp_path / "shards"
    shards.mkdir()
    (shards / "summary-000.json").write_text(
        json.dumps(
            {
                "page_counts": {
                    "aligned": 7,
                    "misaligned": 2,
                    "no_native_text": 1,
                    "low_information": 1,
                }
            }
        )
    )
    (shards / "summary-001.json").write_text(
        json.dumps(
            {
                "page_counts": {
                    "aligned": 3,
                    "processing_error": 1,
                }
            }
        )
    )
    output = tmp_path / "out"
    status = module.aggregate(input_root=shards, output=output)
    report = json.loads((output / "census-summary.json").read_text())
    assert status == 2
    assert report["total_pages"] == 15
    assert report["relevant_pages"] == 13
    assert report["pages_needing_normalization"] == 3
    assert report["processing_errors"] == 1
