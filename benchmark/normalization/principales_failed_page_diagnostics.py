from __future__ import annotations

import difflib
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import pypdfium2 as pdfium
from principales_corpus_suite import _benchmark_identity, _download, _normalize
from scj_page_selection import normalize_native_reference

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json

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


class _FixedReferenceExtractor:
    def __init__(self, reference: SourceTextReference) -> None:
        self.reference = reference

    def extract(self, source: bytes, inspection: object) -> SourceTextReference:
        del source, inspection
        return self.reference


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
        score_payload = asdict(score)
        score_payload["legal_critical_recall"] = score.legal_critical_recall
        no_ocr_score_payload = asdict(no_ocr_score)
        no_ocr_score_payload["legal_critical_recall"] = (
            no_ocr_score.legal_critical_recall
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
                "score": score_payload,
                "no_ocr_diagnostic": {
                    "candidate_characters": len(no_ocr_candidate),
                    "elapsed_seconds": no_ocr_elapsed_seconds,
                    "score": no_ocr_score_payload,
                },
            }
        )
    checks = []
    for item in results:
        score = item["score"]
        reference_path = OUTPUT / (
            f"{item['source_sha256']}-p{int(item['page_index']) + 1}-reference.txt"
        )
        candidate_path = OUTPUT / (
            f"{item['source_sha256']}-p{int(item['page_index']) + 1}-candidate.txt"
        )
        reference_text = reference_path.read_text(encoding="utf-8")
        candidate_text = candidate_path.read_text(encoding="utf-8")
        reference_health = assess_scj_native_reference(reference_text)
        reference = SourceTextReference(
            text=reference_text,
            authority="pdf_native_text_layer",
            risk_flags=reference_health.risk_flags,
        )
        checker = DeterministicSourceFidelityChecker(
            _FixedReferenceExtractor(reference)
        )
        containment = checker.evaluate(
            source=b"",
            inspection=FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            candidate_text=candidate_text,
        )
        if containment is None:
            raise RuntimeError("frozen reference checker unexpectedly returned no result")
        strict_checks = {
            "word_error_rate": float(score["word_error_rate"]) <= MAX_WER,
            "token_content_recall": (
                float(score["token_content_recall"]) >= MIN_CONTENT_RECALL
            ),
            "legal_critical_recall": (
                float(score["legal_critical_recall"]) >= MIN_CRITICAL_RECALL
            ),
        }
        parser_quality_passed = (
            reference.reliable and all(strict_checks.values())
        )
        safely_contained = parser_quality_passed or containment.requires_review
        checks.append(
            {
                "source_sha256": item["source_sha256"],
                "page_index": item["page_index"],
                "reference_reliable": reference.reliable,
                "reference_risk_flags": list(reference.risk_flags),
                **strict_checks,
                "parser_quality_passed": parser_quality_passed,
                "safely_contained": safely_contained,
                "containment_risk_flags": list(containment.risk_flags),
            }
        )
    quality_gate = {
        "passed": all(bool(item["safely_contained"]) for item in checks),
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
            "Known failures pass this regression only when the parser has recovered "
            "or the production source-fidelity gate would contain the page as "
            "quality_review_required. A green regression is therefore a safety claim, "
            "not a claim that Docling itself is perfect. The no-OCR result remains a "
            "challenger used only to isolate whether OCR contributes to divergence."
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
