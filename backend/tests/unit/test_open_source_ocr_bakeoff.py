from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "benchmark" / "normalization"))

from run_open_source_ocr_engine import _extract_strings, _join_lines  # noqa: E402
from score_open_source_ocr_bakeoff import aggregate, score_engine  # noqa: E402


def test_extract_strings_prefers_recognition_texts_without_metadata_noise() -> None:
    payload = {
        "rec_texts": ["PRIMERO: casa", "SCJ-SS-22-0514"],
        "image_path": "/tmp/not-text.png",
        "model": "detector",
    }
    assert _extract_strings(payload) == ["PRIMERO: casa", "SCJ-SS-22-0514"]


def test_join_lines_drops_blank_lines_without_rewriting_text() -> None:
    assert _join_lines(["  PRIMERO: casa  ", "", "SCJ-1"]) == (
        "PRIMERO: casa\nSCJ-1"
    )


def _write_case(
    tmp_path: Path,
    *,
    candidate: str,
    error: str | None = None,
) -> tuple[Path, Path, Path]:
    case_dir = tmp_path / "cases" / "case-0000"
    case_dir.mkdir(parents=True)
    reference = "Sentencia SCJ-SS-22-0514 del 15 de enero de 2026. RD$ 1,500.00."
    (case_dir / "reference-native.txt").write_text(reference, encoding="utf-8")
    manifest = {
        "cases": [
            {
                "sample_id": "case-0000",
                "object_key": "example.pdf",
                "page_index": 10,
                "reference_path": "cases/case-0000/reference-native.txt",
                "reference_reliable": True,
                "reference_authority": "dual_channel_aligned",
            }
        ]
    }
    manifest_path = tmp_path / "prepared-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "sample_id": "case-0000",
                "text": candidate,
                "elapsed_ms": 100,
                "error": error,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime-summary.json"
    runtime.write_text(
        json.dumps(
            {
                "engine": "synthetic",
                "engine_version": "1",
                "pages": 1,
                "successful_pages": 0 if error else 1,
                "failed_pages": 1 if error else 0,
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, predictions, runtime


def test_score_engine_preserves_legal_critical_recall(tmp_path: Path) -> None:
    reference = "Sentencia SCJ-SS-22-0514 del 15 de enero de 2026. RD$ 1,500.00."
    manifest, predictions, runtime = _write_case(
        tmp_path,
        candidate=reference,
    )
    output = tmp_path / "report.json"
    report = score_engine(manifest, predictions, runtime, output)
    assert report["failure_rate"] == 0
    assert report["mean_word_error_rate"] == 0
    assert report["aggregate_legal_critical_recall"] == 1
    assert output.exists()


def test_aggregate_requires_hard_rescue_before_promotion(tmp_path: Path) -> None:
    reports = []
    for engine, wer, critical in (
        ("a", 0.01, 1.0),
        ("b", 0.005, 0.98),
    ):
        path = tmp_path / f"{engine}.json"
        path.write_text(
            json.dumps(
                {
                    "engine": engine,
                    "engine_version": "1",
                    "failure_rate": 0.0,
                    "aggregate_legal_critical_recall": critical,
                    "mean_word_error_rate": wer,
                    "mean_character_error_rate": wer,
                    "mean_elapsed_ms": 100,
                }
            ),
            encoding="utf-8",
        )
        reports.append(path)
    result = aggregate(reports, tmp_path / "aggregate.json")
    assert result["clean_stage_eligible_engines"] == ["a"]
    assert result["promotion_status"] == "hard_rescue_benchmark_required"
