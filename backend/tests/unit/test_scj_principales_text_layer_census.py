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

if importlib.util.find_spec("pypdfium2") is None:
    sys.modules["pypdfium2"] = ModuleType("pypdfium2")


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_principales_text_layer_census.py"
    spec = importlib.util.spec_from_file_location("scj_text_layer_census", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classifies_low_information_and_missing_native(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "run_tesseract_visual_ocr", lambda *_a, **_k: SimpleNamespace(text="", mean_confidence=99.0))
    result = module.classify_page(native_text="", image=b"png")
    assert result["classification"] == "low_information"
    assert len(result["native_text_sha256"]) == 64

    visible = "palabra " * 100
    monkeypatch.setattr(module, "run_tesseract_visual_ocr", lambda *_a, **_k: SimpleNamespace(text=visible, mean_confidence=99.0))
    assert module.classify_page(native_text="", image=b"png")["classification"] == "no_native_text"


def test_verified_runs_split_at_failed_pages() -> None:
    module = _module()
    records = [
        {"page_index": 0, "classification": "aligned"},
        {"page_index": 1, "classification": "aligned"},
        {"page_index": 2, "classification": "misaligned"},
        {"page_index": 3, "classification": "aligned"},
        {"page_index": 4, "classification": "aligned"},
        {"page_index": 5, "classification": "aligned"},
    ]
    assert module._verified_runs(records) == [
        {"start_page_index": 0, "end_page_index": 1, "page_count": 2},
        {"start_page_index": 3, "end_page_index": 5, "page_count": 3},
    ]


def test_document_summary_assigns_complete_and_near_complete_tiers() -> None:
    module = _module()
    complete = [{"page_index": i, "classification": "aligned"} for i in range(10)]
    summary = module._document_summary(key="a.pdf", pdf_sha="a" * 64, page_count=10, records=complete)
    assert summary["verification_tier"] == "verified_complete"
    assert summary["longest_verified_run_pages"] == 10

    near = [{"page_index": i, "classification": "aligned"} for i in range(999)] + [{"page_index": 999, "classification": "misaligned"}]
    summary = module._document_summary(key="b.pdf", pdf_sha="b" * 64, page_count=1000, records=near)
    assert summary["verification_tier"] == "verified_near_complete"
    assert summary["aligned_share_of_relevant"] == pytest.approx(0.999)


def test_aggregate_ranks_documents_and_counts_tiers(tmp_path: Path) -> None:
    module = _module()
    root = tmp_path / "documents"
    for name, ratio, tier, aligned, misaligned, longest in [
        ("a", 1.0, "verified_complete", 10, 0, 10),
        ("b", 0.99, "verified_partial", 99, 1, 50),
    ]:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "document.json").write_text(json.dumps({
            "object_key": f"{name}.pdf",
            "source_pdf_sha256": name * 64,
            "page_count": aligned + misaligned,
            "page_counts": {"aligned": aligned, "misaligned": misaligned},
            "relevant_pages": aligned + misaligned,
            "aligned_share_of_relevant": ratio,
            "verification_tier": tier,
            "verified_runs": [],
            "longest_verified_run_pages": longest,
            "interrupted": False,
        }))
    output = tmp_path / "out"
    assert module.aggregate(input_root=root, output=output) == 0
    report = json.loads((output / "census-summary.json").read_text())
    assert report["documents"] == 2
    assert report["document_ranking"][0]["object_key"] == "a.pdf"
    assert report["verification_tiers"] == {"verified_complete": 1, "verified_partial": 1}
