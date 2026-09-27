from __future__ import annotations

"""Exhaustively classify SCJ Principales PDF pages without paid LLM calls.

Each shard owns whole PDFs, renders every page, runs independent Tesseract OCR,
and compares that visual reading with the PDF native text using the same strict
alignment policy used to admit visual benchmark gold pages.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)
from jurisnexo.normalization.visual_reference_ocr import run_tesseract_visual_ocr

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
POLICY = VisualReferencePolicy()
LOW_INFORMATION_NATIVE_CHARS = 80
LOW_INFORMATION_OCR_CHARS = 80


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list_pdf_keys(store: Any) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": store.config.bucket, "Prefix": PREFIX, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        keys.extend(str(x.get("Key") or "") for x in response.get("Contents", []) if str(x.get("Key") or "").endswith(".pdf"))
        if not response.get("IsTruncated"):
            return sorted(set(keys))
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("S3 listing truncated without continuation token")


def _read_pdf(store: Any, key: str) -> bytes:
    body = store.client.get_object(Bucket=store.config.bucket, Key=key)["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _page_text(page: Any) -> str:
    text_page = page.get_textpage()
    try:
        return text_page.get_text_range()
    finally:
        text_page.close()


def _render(page: Any) -> bytes:
    import io
    bitmap = page.render(scale=2.0)
    try:
        image = bitmap.to_pil()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        bitmap.close()


def classify_page(*, native_text: str, image: bytes) -> dict[str, Any]:
    ocr = run_tesseract_visual_ocr(image, language="spa+eng")
    native_chars = len(native_text.strip())
    ocr_chars = len(ocr.text.strip())
    if native_chars < LOW_INFORMATION_NATIVE_CHARS and ocr_chars < LOW_INFORMATION_OCR_CHARS:
        return {"classification": "low_information", "native_characters": native_chars, "ocr_characters": ocr_chars, "ocr_mean_confidence": ocr.mean_confidence}
    if native_chars < LOW_INFORMATION_NATIVE_CHARS and ocr_chars >= LOW_INFORMATION_OCR_CHARS:
        return {"classification": "no_native_text", "native_characters": native_chars, "ocr_characters": ocr_chars, "ocr_mean_confidence": ocr.mean_confidence}
    assessment = assess_visual_reference_alignment(native_text=native_text, ocr_text=ocr.text, ocr_mean_confidence=ocr.mean_confidence, policy=POLICY)
    return {
        "classification": "aligned" if assessment.accepted else "misaligned",
        "native_characters": native_chars,
        "ocr_characters": ocr_chars,
        "ocr_mean_confidence": ocr.mean_confidence,
        "assessment": assessment.to_json_dict(),
    }


def run(*, shard_index: int, shard_count: int, output: Path) -> int:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard")
    output.mkdir(parents=True, exist_ok=True)
    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    owned = [key for index, key in enumerate(keys) if index % shard_count == shard_index]
    counts: Counter[str] = Counter()
    records_path = output / f"pages-{shard_index:03d}.jsonl"
    with records_path.open("w", encoding="utf-8") as sink:
        for key in owned:
            try:
                pdf_bytes = _read_pdf(store, key)
                document = pdfium.PdfDocument(pdf_bytes)
            except Exception as exc:
                counts["processing_error"] += 1
                sink.write(json.dumps({"object_key": key, "classification": "processing_error", "scope": "document", "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                continue
            try:
                pdf_sha = _sha256(pdf_bytes)
                for page_index in range(len(document)):
                    try:
                        page = document[page_index]
                        try:
                            native_text = _page_text(page)
                            image = _render(page)
                        finally:
                            page.close()
                        result = classify_page(native_text=native_text, image=image)
                    except Exception as exc:
                        result = {"classification": "processing_error", "error": f"{type(exc).__name__}: {exc}"}
                    classification = str(result["classification"])
                    counts[classification] += 1
                    sink.write(json.dumps({"object_key": key, "source_pdf_sha256": pdf_sha, "page_index": page_index, **result}, ensure_ascii=False, sort_keys=True) + "\n")
            finally:
                document.close()
    summary = {"schema_version": 1, "shard_index": shard_index, "shard_count": shard_count, "pdf_objects_total": len(keys), "pdf_objects_owned": len(owned), "page_counts": dict(sorted(counts.items())), "pages_processed": sum(counts.values()), "policy": POLICY.__dict__ if hasattr(POLICY, "__dict__") else {name: getattr(POLICY, name) for name in POLICY.__dataclass_fields__}}
    (output / f"summary-{shard_index:03d}.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if counts["processing_error"] == 0 else 2


def aggregate(*, input_root: Path, output: Path) -> int:
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(input_root.rglob("summary-*.json"))]
    if not summaries:
        raise RuntimeError("no shard summaries found")
    counts: Counter[str] = Counter()
    for summary in summaries:
        counts.update(summary["page_counts"])
    total = sum(counts.values())
    relevant = total - counts["low_information"] - counts["processing_error"]
    needs_normalization = counts["misaligned"] + counts["no_native_text"]
    report = {
        "schema_version": 1,
        "shards": len(summaries),
        "total_pages": total,
        "page_counts": dict(sorted(counts.items())),
        "relevant_pages": relevant,
        "aligned_share_of_relevant": counts["aligned"] / relevant if relevant else 0.0,
        "pages_needing_normalization": needs_normalization,
        "normalization_share_of_relevant": needs_normalization / relevant if relevant else 0.0,
        "processing_errors": counts["processing_error"],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "census-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if counts["processing_error"] == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.aggregate:
        if args.input_root is None:
            parser.error("--input-root is required with --aggregate")
        return aggregate(input_root=args.input_root, output=args.output)
    return run(shard_index=args.shard_index, shard_count=args.shard_count, output=args.output)


if __name__ == "__main__":
    raise SystemExit(main())
