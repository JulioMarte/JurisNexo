from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_single_pdf_parallel_quality.py"
    spec = importlib.util.spec_from_file_location("scj_single_pdf_parallel_quality", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ocr(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "text": "sentencia " * 200,
        "mean_confidence": 96.0,
        "median_confidence": 97.0,
        "p10_confidence": 92.0,
        "low_confidence_word_ratio": 0.01,
        "word_count": 200,
        "engine_version": "tesseract-test",
        "language": "spa+eng",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_quality_route_keeps_alignment_and_tail_risk_separate() -> None:
    module = _module()

    route, reasons = module._quality_route(
        classification="aligned",
        ocr=_ocr(),
        embedded_image_count=1,
    )
    assert route == "accept_candidate"
    assert reasons == []

    route, reasons = module._quality_route(
        classification="aligned",
        ocr=_ocr(p10_confidence=50.0),
        embedded_image_count=0,
    )
    assert route == "sentinel"
    assert "low_p10_ocr_confidence" in reasons

    route, reasons = module._quality_route(
        classification="misaligned",
        ocr=_ocr(),
        embedded_image_count=2,
    )
    assert route == "jev_review"
    assert reasons == ["native_ocr_disagreement", "embedded_images_present"]


def test_diff_segments_are_bounded_and_keep_both_channels() -> None:
    module = _module()
    native = "A" * 400 + "SCJ-SS-22-1191" + "B" * 400
    ocr = "A" * 400 + "SCJ-SS-22-191" + "B" * 400

    segments = module._diff_segments(native, ocr)

    assert 1 <= len(segments) <= module.MAX_DIFF_SEGMENTS
    assert any("1191" in item["native_excerpt"] for item in segments)
    assert any("191" in item["ocr_excerpt"] for item in segments)


def test_aggregate_fails_on_duplicate_or_missing_page_ownership(tmp_path: Path) -> None:
    module = _module()
    source = {
        "object_key": "x.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_count": 3,
        "shard_count": 2,
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    root = tmp_path / "shards"
    root.mkdir()
    (root / "summary-00.json").write_text(
        json.dumps({"shard_index": 0}), encoding="utf-8"
    )
    (root / "summary-01.json").write_text(
        json.dumps({"shard_index": 1}), encoding="utf-8"
    )
    records = [
        {
            "source_pdf_sha256": "a" * 64,
            "page_index": 0,
            "classification": "aligned",
            "quality_route": "accept_candidate",
        },
        {
            "source_pdf_sha256": "a" * 64,
            "page_index": 0,
            "classification": "aligned",
            "quality_route": "accept_candidate",
        },
        {
            "source_pdf_sha256": "a" * 64,
            "page_index": 2,
            "classification": "misaligned",
            "quality_route": "jev_review",
        },
    ]
    (root / "pages-00.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in records),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="page reconciliation failed"):
        module.aggregate(
            source_json=source_path,
            input_root=root,
            output=tmp_path / "out",
        )


def test_aggregate_emits_jev_and_visual_queues(tmp_path: Path) -> None:
    module = _module()
    source = {
        "object_key": "x.pdf",
        "source_pdf_sha256": "b" * 64,
        "page_count": 3,
        "shard_count": 2,
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    root = tmp_path / "shards"
    root.mkdir()
    for index in (0, 1):
        (root / f"summary-{index:02d}.json").write_text(
            json.dumps({"shard_index": index}),
            encoding="utf-8",
        )
    records = [
        {
            "source_pdf_sha256": "b" * 64,
            "page_index": 0,
            "classification": "aligned",
            "quality_route": "accept_candidate",
            "ocr_p10_confidence": 95.0,
        },
        {
            "source_pdf_sha256": "b" * 64,
            "page_index": 1,
            "classification": "misaligned",
            "quality_route": "jev_review",
            "embedded_image_count": 1,
            "ocr_p10_confidence": 80.0,
        },
        {
            "source_pdf_sha256": "b" * 64,
            "page_index": 2,
            "classification": "no_native_text",
            "quality_route": "visual_review",
            "embedded_image_count": 1,
            "ocr_p10_confidence": 70.0,
        },
    ]
    (root / "pages-00.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in records),
        encoding="utf-8",
    )

    output = tmp_path / "out"
    assert module.aggregate(
        source_json=source_path,
        input_root=root,
        output=output,
    ) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete_scan"] is True
    assert summary["jev_review_pages"] == 1
    assert summary["visual_review_pages"] == 2
    assert len((output / "jev-review.jsonl").read_text().splitlines()) == 1
    assert len((output / "visual-review.jsonl").read_text().splitlines()) == 2
