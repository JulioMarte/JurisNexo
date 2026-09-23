from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json
from pypdf import PdfReader, PdfWriter
from scj_page_selection import has_native_text, select_reference_pages

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
OUTPUT = Path(
    os.environ.get(
        "SCJ_PDF_POLICY_HOLDOUT_OUTPUT",
        ".artifacts/scj-principales-pdf-policy-holdout.json",
    )
)
PAGES_PER_DOCUMENT = int(
    os.environ.get("SCJ_PDF_POLICY_PAGES_PER_DOCUMENT", "2")
)
TARGET_DOCUMENTS = int(os.environ.get("SCJ_PDF_POLICY_HOLDOUT_CASES", "6"))
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


def _document_metrics(
    cases: list[PdfPolicyCase],
) -> list[dict[str, object]]:
    grouped: dict[str, list[PdfPolicyCase]] = {}
    for case in cases:
        grouped.setdefault(case.source_sha256, []).append(case)
    documents: list[dict[str, object]] = []
    for sha256, document_cases in grouped.items():
        expected = sum(case.critical_expected_count for case in document_cases)
        matched = sum(case.critical_matched_count for case in document_cases)
        documents.append(
            {
                "source_sha256": sha256,
                "split": document_cases[0].split,
                "page_count": len(document_cases),
                "worst_page_word_error_rate": max(
                    case.word_error_rate for case in document_cases
                ),
                "worst_page_character_error_rate": max(
                    case.character_error_rate for case in document_cases
                ),
                "pages_with_missing_critical": sum(
                    1
                    for case in document_cases
                    if case.critical_matched_count
                    < case.critical_expected_count
                ),
                "aggregate_legal_critical_recall": (
                    1.0
                    if expected == 0
                    else matched / expected
                ),
            }
        )
    documents.sort(key=lambda item: str(item["source_sha256"]))
    return documents


def main() -> int:
    if TARGET_DOCUMENTS < 2 or TARGET_DOCUMENTS > 12:
        raise ValueError(
            "SCJ_PDF_POLICY_HOLDOUT_CASES (documents) must be between 2 and 12"
        )
    if PAGES_PER_DOCUMENT < 1 or PAGES_PER_DOCUMENT > 5:
        raise ValueError(
            "SCJ_PDF_POLICY_PAGES_PER_DOCUMENT must be between 1 and 5"
        )
    if MIN_REFERENCE_CHARS < 200:
        raise ValueError("minimum reference chars must be at least 200")

    store = build_s3_object_store()
    normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
        pdf_aware_ocr=True,
    )

    cases: list[PdfPolicyCase] = []
    attempted = 0
    document_index = 0
    for object_key in _list_pdf_keys(store):
        if document_index >= TARGET_DOCUMENTS:
            break
        if attempted >= MAX_DOCUMENTS_TO_ATTEMPT:
            break
        attempted += 1
        source = _download(store, object_key)
        if not has_native_text(source):
            continue
        pages = select_reference_pages(
            source,
            min_reference_chars=MIN_REFERENCE_CHARS,
            max_pages_to_scan=MAX_PAGES_TO_SCAN,
            max_pages_per_document=PAGES_PER_DOCUMENT,
        )
        if not pages:
            continue
        split = _split(document_index)
        document_index += 1
        source_sha256 = hashlib.sha256(source).hexdigest()
        for page in pages:
            page_pdf = _single_page_pdf(source, page.page_index)

            normalized = normalizer.normalize(
                page_pdf,
                FormatInspection(
                    media_type="application/pdf",
                    detected_format="application/pdf",
                    metadata={},
                ),
                filename=f"{Path(object_key).stem}-p{page.page_index + 1}.pdf",
            )
            if (
                normalized.metadata.get("ocr_policy")
                != "pdf_aware_layout_regions"
            ):
                raise RuntimeError(
                    "production PDF holdout did not use PDF-aware OCR"
                )
            candidate = extract_text_from_structural_json(normalized.payload)
            score = score_text_fidelity(
                expected_text=page.text,
                candidate_text=candidate,
            )
            cases.append(
                PdfPolicyCase(
                    split=split,
                    object_key=object_key,
                    source_sha256=source_sha256,
                    page_index=page.page_index,
                    document_page_count=page.document_page_count,
                    reference_chars=len(page.text),
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
                    reference_text=_diagnostic_text(page.text),
                    candidate_text=_diagnostic_text(candidate),
                )
            )

    if document_index < TARGET_DOCUMENTS:
        raise RuntimeError(
            f"only {document_index} Principales PDFs exposed a native-text "
            "judgment page after front matter"
        )

    calibration = tuple(case for case in cases if case.split == "calibration")
    holdout = tuple(case for case in cases if case.split == "holdout")
    calibration_metrics = _aggregate(calibration)
    holdout_metrics = _aggregate(holdout)
    documents = _document_metrics(cases)
    holdout_documents = tuple(
        document for document in documents if document["split"] == "holdout"
    )
    documents_with_critical_loss = sum(
        1
        for document in holdout_documents
        if int(document["pages_with_missing_critical"]) > 0
    )
    document_pass_rate = (
        1.0
        if not holdout_documents
        else sum(
            1
            for document in holdout_documents
            if int(document["pages_with_missing_critical"]) == 0
        )
        / len(holdout_documents)
    )

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
        "holdout_documents_with_critical_loss": (
            documents_with_critical_loss == 0
        ),
    }
    payload = {
        "schema_version": 2,
        "source": "scj",
        "collection": "principales-sentencias",
        "route_under_test": "production_pdf_aware",
        "pages_per_document": PAGES_PER_DOCUMENT,
        "document_count": document_index,
        "gold_method": (
            "official born-digital PDF native text is the page reference; each "
            "selected page must expose real adjudicative structure (not cover, "
            "credits, ISBN/catalog-card front matter or table of contents), and "
            "up to pages_per_document pages spread across the document are "
            "sampled; each vector-text page is extracted as a one-page PDF and "
            "normalized through the production PDF-aware Docling policy"
        ),
        "calibration": calibration_metrics,
        "holdout": holdout_metrics,
        "document_metrics": {
            "holdout_document_count": len(holdout_documents),
            "holdout_documents_with_critical_loss": documents_with_critical_loss,
            "holdout_document_pass_rate": document_pass_rate,
        },
        "documents": documents,
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
                "max_holdout_documents_with_critical_loss": 0,
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
            "document_metrics tracks worst-page error and any critical loss per "
            "document, because a perfect page average can still hide a document "
            "whose dispositive identifier was damaged."
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
