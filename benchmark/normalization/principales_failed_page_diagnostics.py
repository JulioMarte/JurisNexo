from __future__ import annotations

import difflib
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json
from principales_corpus_suite import _benchmark_identity, _download, _normalize
from scj_page_selection import normalize_native_reference

CASES_PATH = Path(__file__).with_name("principales_failed_pages.json")
OUTPUT = Path(os.environ["FAILURE_DIAGNOSTIC_OUTPUT"])
REQUIRE_PASS = os.environ.get("FAILURE_DIAGNOSTIC_REQUIRE_PASS", "0") == "1"
MAX_WER = float(os.environ.get("FAILURE_DIAGNOSTIC_MAX_WER", "0.10"))
MIN_CONTENT_RECALL = float(
    os.environ.get("FAILURE_DIAGNOSTIC_MIN_CONTENT_RECALL", "0.98")
)
MIN_CRITICAL_RECALL = float(
    os.environ.get("FAILURE_DIAGNOSTIC_MIN_CRITICAL_RECALL", "1.0")
)


def _reference_page(source: bytes, page_index: int) -> str:
    document = pdfium.PdfDocument(source)
    try:
        page = document[page_index]
        try:
            text_page = page.get_textpage()
            try:
                return normalize_native_reference(text_page.get_text_range())
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def main() -> int:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    store = build_s3_object_store()
    normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",), pdf_aware_ocr=True
    )
    no_ocr_normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
        pdf_aware_ocr=True,
        enable_ocr=False,
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for case in fixture["cases"]:
        sha = str(case["source_sha256"])
        page_index = int(case["page_index"])
        key = f"jurisdictions/do/scj/principales-sentencias/{sha[:2]}/{sha}.pdf"
        source = _download(store, key)
        if hashlib.sha256(source).hexdigest() != sha:
            raise RuntimeError(f"source checksum mismatch for {key}")
        reference = _reference_page(source, page_index)
        started = time.perf_counter()
        payload = _normalize(
            route="pdf_aware",
            source=source,
            page_index=page_index,
            object_key=key,
            pdf_normalizer=normalizer,
            ocr_normalizer=normalizer,
        )
        elapsed_seconds = time.perf_counter() - started
        candidate = extract_text_from_structural_json(payload)
        score = score_text_fidelity(
            expected_text=reference, candidate_text=candidate
        )
        no_ocr_started = time.perf_counter()
        no_ocr_payload = _normalize(
            route="pdf_aware",
            source=source,
            page_index=page_index,
            object_key=key,
            pdf_normalizer=no_ocr_normalizer,
            ocr_normalizer=no_ocr_normalizer,
        )
        no_ocr_elapsed_seconds = time.perf_counter() - no_ocr_started
        no_ocr_candidate = extract_text_from_structural_json(no_ocr_payload)
        no_ocr_score = score_text_fidelity(
            expected_text=reference,
            candidate_text=no_ocr_candidate,
        )
        stem = f"{sha}-p{page_index + 1}"
        (OUTPUT / f"{stem}-reference.txt").write_text(
            reference, encoding="utf-8"
        )
        (OUTPUT / f"{stem}-candidate.txt").write_text(
            candidate, encoding="utf-8"
        )
        (OUTPUT / f"{stem}-no-ocr-candidate.txt").write_text(
            no_ocr_candidate, encoding="utf-8"
        )
        diff = difflib.unified_diff(
            reference.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile="native_pdf_reference",
            tofile="pdf_aware_candidate",
        )
        (OUTPUT / f"{stem}-diff.txt").write_text(
            "".join(diff), encoding="utf-8"
        )
        no_ocr_diff = difflib.unified_diff(
            reference.splitlines(keepends=True),
            no_ocr_candidate.splitlines(keepends=True),
            fromfile="native_pdf_reference",
            tofile="docling_no_ocr_candidate",
        )
        (OUTPUT / f"{stem}-no-ocr-diff.txt").write_text(
            "".join(no_ocr_diff), encoding="utf-8"
        )
        results.append(
            {
                "source_sha256": sha,
                "object_key": key,
                "page_index": page_index,
                "reference_kind": "native_pdf_text_unverified_against_image",
                "reference_characters": len(reference),
                "candidate_characters": len(candidate),
                "elapsed_seconds": elapsed_seconds,
                "score": asdict(score),
                "no_ocr_diagnostic": {
                    "candidate_characters": len(no_ocr_candidate),
                    "elapsed_seconds": no_ocr_elapsed_seconds,
                    "score": asdict(no_ocr_score),
                },
            }
        )
    checks = []
    for item in results:
        score = item["score"]
        checks.append(
            {
                "source_sha256": item["source_sha256"],
                "page_index": item["page_index"],
                "word_error_rate": float(score["word_error_rate"]) <= MAX_WER,
                "token_content_recall": (
                    float(score["token_content_recall"]) >= MIN_CONTENT_RECALL
                ),
                "legal_critical_recall": (
                    float(score["legal_critical_recall"]) >= MIN_CRITICAL_RECALL
                ),
            }
        )
    quality_gate = {
        "passed": all(
            all(
                value
                for key, value in item.items()
                if key not in {"source_sha256", "page_index"}
            )
            for item in checks
        ),
        "thresholds": {
            "max_word_error_rate": MAX_WER,
            "min_content_recall": MIN_CONTENT_RECALL,
            "min_legal_critical_recall": MIN_CRITICAL_RECALL,
        },
        "cases": checks,
    }
    report = {
        "source_run": fixture["source_run"],
        "inventory_sha256": fixture["inventory_sha256"],
        "benchmark_identity": _benchmark_identity("pdf_aware"),
        "reference_authority": "native_pdf_text_unverified_against_image",
        "diagnostic_note": (
            "The strict quality gate applies to the production pdf-aware route. "
            "The no-OCR result is a challenger used only to isolate whether OCR "
            "contributes to the known divergence."
        ),
        "quality_gate": quality_gate,
        "cases": results,
    }
    (OUTPUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    if REQUIRE_PASS and not quality_gate["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
