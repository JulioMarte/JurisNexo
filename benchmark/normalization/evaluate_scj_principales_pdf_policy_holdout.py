from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
OUTPUT = Path(
    os.environ.get(
        "SCJ_PDF_POLICY_HOLDOUT_OUTPUT",
        ".artifacts/scj-principales-pdf-policy-holdout.json",
    )
)
TARGET_CASES = int(os.environ.get("SCJ_PDF_POLICY_HOLDOUT_CASES", "6"))
MIN_REFERENCE_CHARS = int(
    os.environ.get("SCJ_PDF_POLICY_HOLDOUT_MIN_REFERENCE_CHARS", "800")
)
MAX_PAGES_TO_SCAN = int(
    os.environ.get("SCJ_PDF_POLICY_HOLDOUT_MAX_PAGES_TO_SCAN", "120")
)
MAX_DOCUMENTS_TO_ATTEMPT = int(
    os.environ.get("SCJ_PDF_POLICY_HOLDOUT_MAX_DOCUMENTS", "40")
)
MAX_HOLDOUT_MEAN_WER = float(
    os.environ.get("SCJ_PDF_POLICY_MAX_HOLDOUT_MEAN_WER", "0.10")
)
MIN_HOLDOUT_CONTENT_RECALL = float(
    os.environ.get("SCJ_PDF_POLICY_MIN_HOLDOUT_CONTENT_RECALL", "0.98")
)
MIN_HOLDOUT_CONTENT_PRECISION = float(
    os.environ.get("SCJ_PDF_POLICY_MIN_HOLDOUT_CONTENT_PRECISION", "0.98")
)
MIN_HOLDOUT_CRITICAL_RECALL = float(
    os.environ.get("SCJ_PDF_POLICY_MIN_HOLDOUT_CRITICAL_RECALL", "1.0")
)
MAX_DIAGNOSTIC_TEXT_CHARS = int(
    os.environ.get("SCJ_PDF_POLICY_MAX_DIAGNOSTIC_TEXT_CHARS", "6000")
)

# Compiled Principales volumes begin with cover, credits, ISBN and library
# catalog-card front matter and a table of contents. Selecting the first page
# with enough native text therefore samples bibliographic front matter, never a
# judgment, and cannot measure legal-document normalization. Require real
# adjudicative structure instead.
_FRONT_MATTER_MARKERS = (
    "isbn",
    "coordinación general",
    "1a. ed.",
    "r426p",
    "índice",
    "indice",
    "impreso en",
    "www.poderjudicial.gob.do",
    "diagramación",
    "división de publicaciones",
    "división de jurisprudencia",
    "catalogación",
    "edición:",
    "ejemplares",
)
_NATIVE_ARTIFACT = "\ufffe"


def _normalize_native_reference(text: str) -> str:
    # pypdfium2 emits U+FFFE for glyphs it cannot decode (frequently a
    # line-break hyphen). Removing it avoids charging a reference artifact to
    # the candidate as a fidelity error.
    return text.replace(_NATIVE_ARTIFACT, "").strip()


def _looks_like_body_page(text: str) -> bool:
    folded = text.casefold()
    if any(marker in folded for marker in _FRONT_MATTER_MARKERS):
        return False
    if folded.count("considerando") >= 2:
        return True
    if "en nombre de la república" in folded:
        return True
    return "vistos" in folded and ("falla" in folded or "fallamos" in folded)


@dataclass(frozen=True, slots=True)
class PdfPolicyCase:
    split: str
    object_key: str
    source_sha256: str
    page_index: int
    document_page_count: int
    reference_chars: int
    candidate_chars: int
    character_error_rate: float
    word_error_rate: float
    token_content_recall: float
    token_content_precision: float
    token_content_f1: float
    token_order_preservation: float
    legal_critical_recall: float
    critical_expected_count: int
    critical_matched_count: int
    reference_text: str
    candidate_text: str


def _list_pdf_keys(store: Any) -> tuple[str, ...]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": PREFIX,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if key.endswith(".pdf"):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing omitted continuation token")
    return tuple(sorted(keys))


def _download(store: Any, key: str) -> bytes:
    response = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )
    payload = response["Body"].read()
    return payload if isinstance(payload, bytes) else bytes(payload)


def _reference_page(pdf_bytes: bytes) -> tuple[int, str, int] | None:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page_count = len(document)
        page_limit = min(page_count, MAX_PAGES_TO_SCAN)
        for page_index in range(page_limit):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    reference = _normalize_native_reference(
                        text_page.get_text_range()
                    )
                finally:
                    text_page.close()
                if len(reference) < MIN_REFERENCE_CHARS:
                    continue
                if not _looks_like_body_page(reference):
                    continue
                return page_index, reference, page_count
            finally:
                page.close()
    finally:
        document.close()
    return None


def _has_native_text(pdf_bytes: bytes, probe_pages: int = 3) -> bool:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for page_index in range(min(len(document), probe_pages)):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    if len(text_page.get_text_range().strip()) >= 200:
                        return True
                finally:
                    text_page.close()
            finally:
                page.close()
    finally:
        document.close()
    return False


def _single_page_pdf(pdf_bytes: bytes, page_index: int) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    output = io.BytesIO()
    writer.write(output)
    payload = output.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("single-page PDF extraction did not produce a PDF")
    return payload


def _split(index: int) -> str:
    return "calibration" if index % 2 == 0 else "holdout"


def _diagnostic_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= MAX_DIAGNOSTIC_TEXT_CHARS:
        return normalized
    return normalized[:MAX_DIAGNOSTIC_TEXT_CHARS] + "…[truncated]"


def _aggregate(items: tuple[PdfPolicyCase, ...]) -> dict[str, float | int]:
    critical_expected = sum(item.critical_expected_count for item in items)
    critical_matched = sum(item.critical_matched_count for item in items)
    return {
        "case_count": len(items),
        "mean_character_error_rate": (
            sum(item.character_error_rate for item in items) / len(items)
        ),
        "mean_word_error_rate": (
            sum(item.word_error_rate for item in items) / len(items)
        ),
        "mean_token_content_recall": (
            sum(item.token_content_recall for item in items) / len(items)
        ),
        "mean_token_content_precision": (
            sum(item.token_content_precision for item in items) / len(items)
        ),
        "mean_token_content_f1": (
            sum(item.token_content_f1 for item in items) / len(items)
        ),
        "mean_token_order_preservation": (
            sum(item.token_order_preservation for item in items) / len(items)
        ),
        "critical_expected_count": critical_expected,
        "critical_matched_count": critical_matched,
        "aggregate_legal_critical_recall": (
            1.0
            if critical_expected == 0
            else critical_matched / critical_expected
        ),
    }


def main() -> int:
    if TARGET_CASES < 4 or TARGET_CASES > 12:
        raise ValueError("SCJ_PDF_POLICY_HOLDOUT_CASES must be between 4 and 12")
    if MIN_REFERENCE_CHARS < 200:
        raise ValueError("minimum reference chars must be at least 200")

    store = build_s3_object_store()
    normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
        pdf_aware_ocr=True,
    )

    cases: list[PdfPolicyCase] = []
    attempted = 0
    for object_key in _list_pdf_keys(store):
        if len(cases) >= TARGET_CASES:
            break
        if attempted >= MAX_DOCUMENTS_TO_ATTEMPT:
            break
        attempted += 1
        source = _download(store, object_key)
        if not _has_native_text(source):
            continue
        reference_page = _reference_page(source)
        if reference_page is None:
            continue
        page_index, reference, document_page_count = reference_page
        page_pdf = _single_page_pdf(source, page_index)

        normalized = normalizer.normalize(
            page_pdf,
            FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            filename=f"{Path(object_key).stem}-p{page_index + 1}.pdf",
        )
        if normalized.metadata.get("ocr_policy") != "pdf_aware_layout_regions":
            raise RuntimeError("production PDF holdout did not use PDF-aware OCR")
        candidate = extract_text_from_structural_json(normalized.payload)
        score = score_text_fidelity(
            expected_text=reference,
            candidate_text=candidate,
        )
        cases.append(
            PdfPolicyCase(
                split=_split(len(cases)),
                object_key=object_key,
                source_sha256=hashlib.sha256(source).hexdigest(),
                page_index=page_index,
                document_page_count=document_page_count,
                reference_chars=len(reference),
                candidate_chars=len(candidate),
                character_error_rate=score.character_error_rate,
                word_error_rate=score.word_error_rate,
                token_content_recall=score.token_content_recall,
                token_content_precision=score.token_content_precision,
                token_content_f1=score.token_content_f1,
                token_order_preservation=score.token_order_preservation,
                legal_critical_recall=score.legal_critical_recall,
                critical_expected_count=sum(
                    item.expected for item in score.critical.values()
                ),
                critical_matched_count=sum(
                    item.matched for item in score.critical.values()
                ),
                reference_text=_diagnostic_text(reference),
                candidate_text=_diagnostic_text(candidate),
            )
        )

    if len(cases) < TARGET_CASES:
        raise RuntimeError(
            f"only {len(cases)} Principales PDFs exposed a native-text "
            "judgment page after front matter"
        )

    calibration = tuple(case for case in cases if case.split == "calibration")
    holdout = tuple(case for case in cases if case.split == "holdout")
    calibration_metrics = _aggregate(calibration)
    holdout_metrics = _aggregate(holdout)

    checks = {
        "mean_word_error_rate": (
            float(holdout_metrics["mean_word_error_rate"])
            <= MAX_HOLDOUT_MEAN_WER
        ),
        "mean_token_content_recall": (
            float(holdout_metrics["mean_token_content_recall"])
            >= MIN_HOLDOUT_CONTENT_RECALL
        ),
        "mean_token_content_precision": (
            float(holdout_metrics["mean_token_content_precision"])
            >= MIN_HOLDOUT_CONTENT_PRECISION
        ),
        "aggregate_legal_critical_recall": (
            float(holdout_metrics["aggregate_legal_critical_recall"])
            >= MIN_HOLDOUT_CRITICAL_RECALL
        ),
    }
    payload = {
        "schema_version": 1,
        "source": "scj",
        "collection": "principales-sentencias",
        "route_under_test": "production_pdf_aware",
        "gold_method": (
            "official born-digital PDF native text is the page reference; the "
            "selected page must expose real adjudicative structure (not cover, "
            "credits, ISBN/catalog-card front matter or table of contents); "
            "that same vector-text page is extracted as a one-page PDF and "
            "normalized through the production PDF-aware Docling policy"
        ),
        "calibration": calibration_metrics,
        "holdout": holdout_metrics,
        "quality_gate": {
            "passed": all(checks.values()),
            "checks": checks,
            "thresholds": {
                "max_mean_word_error_rate": MAX_HOLDOUT_MEAN_WER,
                "min_mean_token_content_recall": MIN_HOLDOUT_CONTENT_RECALL,
                "min_mean_token_content_precision": (
                    MIN_HOLDOUT_CONTENT_PRECISION
                ),
                "min_aggregate_legal_critical_recall": (
                    MIN_HOLDOUT_CRITICAL_RECALL
                ),
            },
        },
        "cases": [asdict(case) for case in cases],
        "diagnostics": (
            "Each case exports reference_text and candidate_text so a human "
            "can adjudicate reading order directly. token_order_preservation "
            "is the longest-common-subsequence ratio of content tokens: near "
            "1.0 means content survived in order; a low value with high "
            "token_content_recall/precision means content is present but "
            "reordered. The reference is pypdfium2 content-stream order, "
            "which is not guaranteed to equal logical reading order. "
            "document_page_count and page_index record where the selected "
            "judgment page sits in the source volume."
        ),
        "limitations": (
            "This proves the born-digital Principales production route only. "
            "It does not prove full-page OCR quality for scanned/historical material."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if bool(payload["quality_gate"]["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
