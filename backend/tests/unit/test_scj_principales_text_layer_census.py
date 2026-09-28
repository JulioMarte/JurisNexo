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
    path = (
        REPO_ROOT
        / "backend"
        / "scripts"
        / "scj_principales_text_layer_census.py"
    )
    spec = importlib.util.spec_from_file_location(
        "scj_text_layer_census",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classifies_low_information_and_missing_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "run_tesseract_visual_ocr",
        lambda *_a, **_k: SimpleNamespace(
            text="",
            mean_confidence=99.0,
        ),
    )
    result = module.classify_page(native_text="", image=b"png")
    assert result["classification"] == "low_information"
    assert len(result["native_text_sha256"]) == 64

    visible = "palabra " * 100
    monkeypatch.setattr(
        module,
        "run_tesseract_visual_ocr",
        lambda *_a, **_k: SimpleNamespace(
            text=visible,
            mean_confidence=99.0,
        ),
    )
    result = module.classify_page(native_text="", image=b"png")
    assert result["classification"] == "no_native_text"


def test_source_identity_drift_fails_closed() -> None:
    module = _module()

    class Body:
        def read(self) -> bytes:
            return b"pdf-bytes"

    class Client:
        def get_object(self, **_kwargs: object) -> dict[str, object]:
            return {
                "Body": Body(),
                "ContentLength": 9,
                "ETag": '"etag-v2"',
            }

    store = SimpleNamespace(
        client=Client(),
        config=SimpleNamespace(bucket="bucket"),
    )

    with pytest.raises(RuntimeError, match="ETag drift"):
        module._read_pdf(
            store,
            "document.pdf",
            expected_size=9,
            expected_etag="etag-v1",
        )


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
        {
            "start_page_index": 0,
            "end_page_index": 1,
            "page_count": 2,
        },
        {
            "start_page_index": 3,
            "end_page_index": 5,
            "page_count": 3,
        },
    ]


def test_document_summary_requires_complete_scan_for_complete_tier() -> None:
    module = _module()
    records = [
        {"page_index": index, "classification": "aligned"}
        for index in range(10)
    ]

    summary = module._document_summary(
        key="a.pdf",
        pdf_sha="a" * 64,
        source_page_count=10,
        records=records,
    )
    assert summary["verification_tier"] == "verified_complete"
    assert summary["complete_scan"] is True
    assert summary["longest_verified_run_pages"] == 10

    incomplete = module._document_summary(
        key="a.pdf",
        pdf_sha="a" * 64,
        source_page_count=11,
        records=records,
    )
    assert incomplete["verification_tier"] == "unsuitable"
    assert incomplete["complete_scan"] is False


def test_document_summary_assigns_near_complete_tier() -> None:
    module = _module()
    records = [
        {"page_index": index, "classification": "aligned"}
        for index in range(999)
    ]
    records.append(
        {
            "page_index": 999,
            "classification": "misaligned",
            "assessment": {
                "score": {
                    "word_error_rate": 0.11,
                    "character_error_rate": 0.09,
                    "legal_critical_recall": 1.0,
                }
            },
        }
    )

    summary = module._document_summary(
        key="b.pdf",
        pdf_sha="b" * 64,
        source_page_count=1000,
        records=records,
    )
    assert summary["verification_tier"] == "verified_near_complete"
    assert summary["aligned_share_of_relevant"] == pytest.approx(0.999)
    assert summary["longest_problem_run_pages"] == 1


def test_aggregate_rejects_missing_inventory_documents(
    tmp_path: Path,
) -> None:
    module = _module()
    root = tmp_path / "documents"
    document_dir = root / "a"
    document_dir.mkdir(parents=True)
    (document_dir / "document.json").write_text(
        json.dumps(
            {
                "object_key": "a.pdf",
                "source_pdf_sha256": "a" * 64,
                "source_page_count": 10,
                "processed_pages": 10,
                "complete_scan": True,
                "page_counts": {"aligned": 10},
                "relevant_pages": 10,
                "aligned_share_of_relevant": 1.0,
                "verification_tier": "verified_complete",
                "verified_runs": [],
                "longest_verified_run_pages": 10,
                "interrupted": False,
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "inventory_sha256": "frozen",
                "documents": [
                    {"object_key": "a.pdf"},
                    {"object_key": "b.pdf"},
                ],
            }
        ),
        encoding="utf-8",
    )

    output = tmp_path / "out"
    status = module.aggregate(
        input_root=root,
        output=output,
        inventory_path=inventory_path,
    )
    report = json.loads(
        (output / "census-summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert status == 2
    assert report["documents"] == 1
    assert report["expected_documents"] == 2
    assert report["missing_documents"] == ["b.pdf"]
