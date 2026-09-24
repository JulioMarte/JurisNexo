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
        stem = f"{sha}-p{page_index + 1}"
        (OUTPUT / f"{stem}-reference.txt").write_text(
            reference, encoding="utf-8"
        )
        (OUTPUT / f"{stem}-candidate.txt").write_text(
            candidate, encoding="utf-8"
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
            }
        )
    report = {
        "source_run": fixture["source_run"],
        "inventory_sha256": fixture["inventory_sha256"],
        "benchmark_identity": _benchmark_identity("pdf_aware"),
        "cases": results,
    }
    (OUTPUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
