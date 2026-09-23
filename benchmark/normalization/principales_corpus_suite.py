from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.benchmark_suite import (
    SuiteRecord,
    aggregate_records,
    format_summary,
    parse_configs,
    resume_key,
)
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json
from scj_page_selection import has_native_text, select_reference_pages

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
CHECKPOINT_PREFIX = "derived/normalization/benchmark/principales-corpus-suite/"
CHECKPOINT_KEY = f"{CHECKPOINT_PREFIX}latest/records.jsonl"

OUTPUT_DIR = Path(
    os.environ.get("SUITE_OUTPUT_DIR", ".artifacts/principales-corpus-suite")
)
CONFIGS = os.environ.get("SUITE_CONFIGS", "pdf_aware")
DOCUMENT_LIMIT = int(os.environ.get("SUITE_DOCUMENT_LIMIT", "25"))
PAGES_PER_DOCUMENT = int(os.environ.get("SUITE_PAGES_PER_DOCUMENT", "3"))
MAX_PAGES_TO_SCAN = int(os.environ.get("SUITE_MAX_PAGES_TO_SCAN", "120"))
MIN_REFERENCE_CHARS = int(os.environ.get("SUITE_MIN_REFERENCE_CHARS", "800"))
RESUME = os.environ.get("SUITE_RESUME", "1") == "1"
OCR_LANGUAGE_TAGS = ("iso:es",)


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
    payload = store.client.get_object(
        Bucket=store.config.bucket, Key=key
    )["Body"].read()
    return payload if isinstance(payload, bytes) else bytes(payload)


def _single_page_pdf(pdf_bytes: bytes, page_index: int) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    output = io.BytesIO()
    writer.write(output)
    payload = output.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("single-page PDF extraction did not produce a PDF")
    return payload


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            image = page.render(scale=1.5).to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _normalize(
    *,
    route: str,
    source: bytes,
    page_index: int,
    object_key: str,
    pdf_normalizer: DoclingStructuralNormalizer,
    ocr_normalizer: DoclingStructuralNormalizer,
) -> bytes:
    if route == "pdf_aware":
        page_pdf = _single_page_pdf(source, page_index)
        normalized = pdf_normalizer.normalize(
            page_pdf,
            FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            filename=f"{Path(object_key).stem}-p{page_index + 1}.pdf",
        )
        return normalized.payload
    page_png = _render_page(source, page_index)
    normalized = ocr_normalizer.normalize(
        page_png,
        FormatInspection(
            media_type="image/png",
            detected_format="image/png",
            metadata={},
        ),
        filename=f"{Path(object_key).stem}-p{page_index + 1}.png",
    )
    return normalized.payload


def _load_existing(store: Any) -> tuple[list[SuiteRecord], set[str]]:
    records: list[SuiteRecord] = []
    keys: set[str] = set()
    if not RESUME:
        return records, keys
    try:
        payload = store.client.get_object(
            Bucket=store.config.bucket, Key=CHECKPOINT_KEY
        )["Body"].read()
    except Exception:  # noqa: BLE001 - a missing checkpoint is a normal cold start
        return records, keys
    text = (
        payload.decode("utf-8")
        if isinstance(payload, bytes)
        else str(payload)
    )
    for line in text.splitlines():
        if not line.strip():
            continue
        record = SuiteRecord(**json.loads(line))
        records.append(record)
        keys.add(
            resume_key(record.config, record.source_sha256, record.page_index)
        )
    return records, keys


def main() -> int:
    if DOCUMENT_LIMIT < 1:
        raise ValueError("SUITE_DOCUMENT_LIMIT must be at least 1")
    if PAGES_PER_DOCUMENT < 1 or PAGES_PER_DOCUMENT > 10:
        raise ValueError("SUITE_PAGES_PER_DOCUMENT must be between 1 and 10")

    configs = parse_configs(CONFIGS)
    store = build_s3_object_store()
    records, completed = _load_existing(store)

    pdf_normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=OCR_LANGUAGE_TAGS,
        pdf_aware_ocr=True,
    )
    ocr_normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=OCR_LANGUAGE_TAGS,
    )

    keys = _list_pdf_keys(store)
    if len(keys) < DOCUMENT_LIMIT:
        raise RuntimeError(
            f"expected at least {DOCUMENT_LIMIT} Principales PDFs, "
            f"found {len(keys)}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUTPUT_DIR / "records.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as stream:
        document_index = 0
        for object_key in keys:
            if document_index >= DOCUMENT_LIMIT:
                break
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
            document_index += 1
            source_sha256 = hashlib.sha256(source).hexdigest()
            for page in pages:
                for config in configs:
                    key = resume_key(config, source_sha256, page.page_index)
                    if key in completed:
                        continue
                    started = time.perf_counter()
                    payload = _normalize(
                        route=config,
                        source=source,
                        page_index=page.page_index,
                        object_key=object_key,
                        pdf_normalizer=pdf_normalizer,
                        ocr_normalizer=ocr_normalizer,
                    )
                    elapsed = time.perf_counter() - started
                    candidate = extract_text_from_structural_json(payload)
                    score = score_text_fidelity(
                        expected_text=page.text,
                        candidate_text=candidate,
                    )
                    record = SuiteRecord(
                        config=config,
                        source_sha256=source_sha256,
                        object_key=object_key,
                        page_index=page.page_index,
                        document_page_count=page.document_page_count,
                        elapsed_seconds=elapsed,
                        output_bytes=len(payload),
                        character_error_rate=score.character_error_rate,
                        word_error_rate=score.word_error_rate,
                        token_content_recall=score.token_content_recall,
                        token_content_precision=score.token_content_precision,
                        token_order_preservation=(
                            score.token_order_preservation
                        ),
                        legal_critical_recall=score.legal_critical_recall,
                        critical_expected_count=sum(
                            item.expected for item in score.critical.values()
                        ),
                        critical_matched_count=sum(
                            item.matched for item in score.critical.values()
                        ),
                    )
                    records.append(record)
                    completed.add(key)
                    stream.write(
                        json.dumps(
                            asdict(record), ensure_ascii=False, sort_keys=True
                        )
                        + "\n"
                    )
                    stream.flush()

    report = aggregate_records(records)
    report_payload = {
        "schema_version": 1,
        "configs": list(configs),
        "document_limit": DOCUMENT_LIMIT,
        "pages_per_document": PAGES_PER_DOCUMENT,
        "recorded": len(records),
        "report": report,
    }
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    summary = format_summary(report, recorded=len(records))
    (OUTPUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True))

    store.put(
        key=CHECKPOINT_KEY,
        content=jsonl_path.read_bytes(),
        content_type="application/x-ndjson",
        metadata={"recorded": str(len(records))},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
