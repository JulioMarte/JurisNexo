from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scj_page_selection import has_native_text, select_reference_page

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
OUTPUT = Path(
    os.environ.get(
        "SCJ_NORMALIZATION_HOLDOUT_OUTPUT",
        ".artifacts/scj-principales-ocr-holdout.json",
    )
)
TARGET_CASES = int(os.environ.get("SCJ_NORMALIZATION_HOLDOUT_CASES", "6"))
MIN_REFERENCE_CHARS = int(
    os.environ.get("SCJ_NORMALIZATION_HOLDOUT_MIN_REFERENCE_CHARS", "800")
)
MAX_PAGES_TO_SCAN = int(
    os.environ.get("SCJ_NORMALIZATION_HOLDOUT_MAX_PAGES_TO_SCAN", "120")
)
MAX_DOCUMENTS_TO_ATTEMPT = int(
    os.environ.get("SCJ_NORMALIZATION_HOLDOUT_MAX_DOCUMENTS", "40")
)
MAX_HOLDOUT_MEAN_WER = float(
    os.environ.get("SCJ_NORMALIZATION_MAX_HOLDOUT_MEAN_WER", "0.20")
)
MIN_HOLDOUT_CONTENT_RECALL = float(
    os.environ.get("SCJ_NORMALIZATION_MIN_HOLDOUT_CONTENT_RECALL", "0.95")
)
MIN_HOLDOUT_CONTENT_PRECISION = float(
    os.environ.get("SCJ_NORMALIZATION_MIN_HOLDOUT_CONTENT_PRECISION", "0.95")
)
MIN_HOLDOUT_CRITICAL_RECALL = float(
    os.environ.get("SCJ_NORMALIZATION_MIN_HOLDOUT_CRITICAL_RECALL", "1.0")
)


@dataclass(frozen=True, slots=True)
class OcrCase:
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
    missing_span_count: int
    critical: dict[str, dict[str, float | int]]


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


def _reference_page(pdf_bytes: bytes) -> tuple[int, str, bytes, int] | None:
    import pypdfium2 as pdfium

    selected = select_reference_page(
        pdf_bytes,
        min_reference_chars=MIN_REFERENCE_CHARS,
        max_pages_to_scan=MAX_PAGES_TO_SCAN,
    )
    if selected is None:
        return None
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[selected.page_index]
        try:
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return (
                selected.page_index,
                selected.text,
                buffer.getvalue(),
                selected.document_page_count,
            )
        finally:
            page.close()
    finally:
        document.close()


def _critical_payload(score: Any) -> dict[str, dict[str, float | int]]:
    return {
        category: {
            "expected": item.expected,
            "matched": item.matched,
            "recall": item.recall,
        }
        for category, item in score.critical.items()
    }


def _split(index: int) -> str:
    return "calibration" if index % 2 == 0 else "holdout"


def main() -> int:
    if TARGET_CASES < 4 or TARGET_CASES > 12:
        raise ValueError("SCJ_NORMALIZATION_HOLDOUT_CASES must be between 4 and 12")
    if MIN_REFERENCE_CHARS < 200:
        raise ValueError("minimum reference chars must be at least 200")

    store = build_s3_object_store()
    normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
    )

    cases: list[OcrCase] = []
    attempted = 0
    for object_key in _list_pdf_keys(store):
        if len(cases) >= TARGET_CASES:
            break
        if attempted >= MAX_DOCUMENTS_TO_ATTEMPT:
            break
        attempted += 1
        source = _download(store, object_key)
        if not has_native_text(source):
            continue
        reference_page = _reference_page(source)
        if reference_page is None:
            continue
        page_index, reference, image, document_page_count = reference_page

        normalized = normalizer.normalize(
            image,
            FormatInspection(
                media_type="image/png",
                detected_format="image/png",
                metadata={},
            ),
            filename=f"{Path(object_key).stem}-p{page_index + 1}.png",
        )
        candidate = extract_text_from_structural_json(normalized.payload)
        score = score_text_fidelity(
            expected_text=reference,
            candidate_text=candidate,
        )
        cases.append(
            OcrCase(
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
                missing_span_count=score.missing_span_count,
                critical=_critical_payload(score),
            )
        )

    if len(cases) < TARGET_CASES:
        raise RuntimeError(
            f"only {len(cases)} Principales documents exposed a native-text "
            "judgment page after front matter"
        )

    calibration = tuple(case for case in cases if case.split == "calibration")
    holdout = tuple(case for case in cases if case.split == "holdout")

    def aggregate(items: tuple[OcrCase, ...]) -> dict[str, float | int]:
        critical_expected = sum(
            item.critical_expected_count for item in items
        )
        critical_matched = sum(
            item.critical_matched_count for item in items
        )
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

    payload = {
        "schema_version": 1,
        "source": "scj",
        "collection": "principales-sentencias",
        "gold_method": (
            "official born-digital PDF native text used as reference; the "
            "selected page must expose real adjudicative structure (not cover, "
            "credits, ISBN/catalog-card front matter or table of contents); "
            "that same page is rendered to PNG and OCR-normalized"
        ),
        "limitations": (
            "This is source-derived OCR gold for born-digital Principales "
            "judgment pages. It does not replace human-verified gold for "
            "historically scanned material."
        ),
        "calibration": aggregate(calibration),
        "holdout": aggregate(holdout),
        "cases": [asdict(case) for case in cases],
    }
    holdout_metrics = payload["holdout"]
    gate_checks = {
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
    payload["quality_gate"] = {
        "passed": all(gate_checks.values()),
        "checks": gate_checks,
        "thresholds": {
            "max_mean_word_error_rate": MAX_HOLDOUT_MEAN_WER,
            "min_mean_token_content_recall": MIN_HOLDOUT_CONTENT_RECALL,
            "min_mean_token_content_precision": MIN_HOLDOUT_CONTENT_PRECISION,
            "min_aggregate_legal_critical_recall": (
                MIN_HOLDOUT_CRITICAL_RECALL
            ),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))

    quality_gate = payload["quality_gate"]
    return 0 if bool(quality_gate["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
