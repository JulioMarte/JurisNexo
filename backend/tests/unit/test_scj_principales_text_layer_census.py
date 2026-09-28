from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))

# The census module imports pypdfium2, which belongs to the optional
# "normalization" extra that the generic test image intentionally omits. These
# logic tests never render PDFs, and the dedicated census workflow installs the
# real dependency. Stub the renderer boundary when absent so classification and
# aggregation contracts still execute in the generic suite.
if importlib.util.find_spec("pypdfium2") is None:
    sys.modules["pypdfium2"] = ModuleType("pypdfium2")


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_principales_text_layer_census.py"
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


def test_resume_checkpoint_reconstructs_completed_pages_and_counts(
    tmp_path: Path,
) -> None:
    module = _module()
    records = tmp_path / "pages-000.jsonl"
    records.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "object_key": "a.pdf",
                        "page_index": 0,
                        "classification": "aligned",
                    }
                ),
                json.dumps(
                    {
                        "object_key": "a.pdf",
                        "page_index": 1,
                        "classification": "misaligned",
                    }
                ),
                json.dumps(
                    {
                        "object_key": "b.pdf",
                        "page_index": 0,
                        "classification": "low_information",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    completed, counts = module._load_completed(records)
    assert completed == {("a.pdf", 0), ("a.pdf", 1), ("b.pdf", 0)}
    assert counts["aligned"] == 1
    assert counts["misaligned"] == 1
    assert counts["low_information"] == 1


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
                },
                "interrupted": False,
            }
        )
    )
    (shards / "summary-001.json").write_text(
        json.dumps(
            {
                "page_counts": {
                    "aligned": 3,
                    "processing_error": 1,
                },
                "interrupted": False,
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
    assert report["interrupted_shards"] == 0