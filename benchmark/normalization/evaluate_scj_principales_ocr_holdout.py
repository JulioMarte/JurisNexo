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
    os.environ.get("SCJ_NORMALIZATION_HOLDOUT_MAX_PAGES_TO_SCAN", "6")
)


@dataclass(frozen=True, slots=True)
class OcrCase:
    split: str
    object_key: str
    source_sha256: str
    page_index: int
    reference_chars: int
    candidate_chars: int
    character_error_rate: float
    word_error_rate: float
    legal_critical_recall: float
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


def _reference_page(pdf_bytes: bytes) -> tuple[int, str, bytes] | None:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page_limit = min(len(document), MAX_PAGES_TO_SCAN)
        for page_index in range(page_limit):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    reference = text_page.get_text_range().strip()
                finally:
                    text_page.close()
                if len(reference) < MIN_REFERENCE_CHARS:
                    continue
                bitmap = page.render(scale=1.5)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                return page_index, reference, buffer.getvalue()
            finally:
                page.close()
    finally:
        document.close()
    return None


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
    for object_key in _list_pdf_keys(store):
        if len(cases) >= TARGET_CASES:
            break
        source = _download(store, object_key)
        reference_page = _reference_page(source)
        if reference_page is None:
            continue
        page_index, reference, image = reference_page

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
                reference_chars=len(reference),
                candidate_chars=len(candidate),
                character_error_rate=score.character_error_rate,
                word_error_rate=score.word_error_rate,
                legal_critical_recall=score.legal_critical_recall,
                missing_span_count=score.missing_span_count,
                critical=_critical_payload(score),
            )
        )

    if len(cases) < TARGET_CASES:
        raise RuntimeError(
            f"only {len(cases)} Principales documents exposed suitable native-text pages"
        )

    calibration = tuple(case for case in cases if case.split == "calibration")
    holdout = tuple(case for case in cases if case.split == "holdout")

    def aggregate(items: tuple[OcrCase, ...]) -> dict[str, float | int]:
        return {
            "case_count": len(items),
            "mean_character_error_rate": (
                sum(item.character_error_rate for item in items) / len(items)
            ),
            "mean_word_error_rate": (
                sum(item.word_error_rate for item in items) / len(items)
            ),
            "mean_legal_critical_recall": (
                sum(item.legal_critical_recall for item in items) / len(items)
            ),
            "minimum_legal_critical_recall": min(
                item.legal_critical_recall for item in items
            ),
        }

    payload = {
        "schema_version": 1,
        "source": "scj",
        "collection": "principales-sentencias",
        "gold_method": (
            "official born-digital PDF native text used as reference; "
            "the same page is rendered to PNG and OCR-normalized"
        ),
        "limitations": (
            "This is source-derived OCR gold for born-digital Principales pages. "
            "It does not replace human-verified gold for historically scanned material."
        ),
        "calibration": aggregate(calibration),
        "holdout": aggregate(holdout),
        "cases": [asdict(case) for case in cases],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))

    # The first run is measurement, not a hidden quality-policy promotion.
    # Fail only when the holdout is structurally unusable or has zero critical fidelity.
    return (
        0
        if all(
            (
                float(payload["holdout"]["mean_word_error_rate"]) < 1.0,
                float(payload["holdout"]["mean_legal_critical_recall"]) > 0.0,
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
