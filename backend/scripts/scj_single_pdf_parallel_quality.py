"""Parallel page-quality census for one immutable SCJ Principales PDF.

The workflow downloads the source once, fans page ownership out across isolated
GitHub jobs, and then reconciles all shards. Deterministic evidence decides only
whether a page is a strong acceptance candidate or needs semantic/visual review;
models never overwrite source text.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)
from jurisnexo.normalization.visual_reference_ocr import (
    VisualOcrObservation,
    run_tesseract_visual_ocr,
)

RENDER_SCALE = 2.0
OCR_LANGUAGE = "spa+eng"
OCR_PAGE_SEGMENTATION_MODE = 6
LOW_INFORMATION_NATIVE_CHARS = 80
LOW_INFORMATION_OCR_CHARS = 80
STRONG_P10_CONFIDENCE = 75.0
STRONG_LOW_CONFIDENCE_WORD_RATIO = 0.10
DIFF_CONTEXT_CHARS = 220
MAX_DIFF_SEGMENTS = 6
POLICY = VisualReferencePolicy()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _normalized_etag(value: object) -> str:
    return str(value or "").strip().strip('"')


def prepare_source(*, object_key: str, output: Path, shard_count: int) -> dict[str, Any]:
    if shard_count < 1 or shard_count > 64:
        raise ValueError("shard_count must be between 1 and 64")
    store = build_s3_object_store()
    response = store.client.get_object(Bucket=store.config.bucket, Key=object_key)
    body = response["Body"].read()
    payload = body if isinstance(body, bytes) else bytes(body)
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("selected source is not a PDF")

    document = pdfium.PdfDocument(payload)
    try:
        page_count = len(document)
    finally:
        document.close()
    if page_count < 1:
        raise RuntimeError("selected PDF has no pages")

    output.mkdir(parents=True, exist_ok=True)
    source_path = output / "source.pdf"
    source_path.write_bytes(payload)
    source = {
        "schema_version": 1,
        "object_key": object_key,
        "source_pdf_sha256": _sha256(payload),
        "size_bytes": len(payload),
        "etag": _normalized_etag(response.get("ETag")),
        "page_count": page_count,
        "shard_count": shard_count,
        "render_scale": RENDER_SCALE,
        "ocr_language": OCR_LANGUAGE,
        "ocr_page_segmentation_mode": OCR_PAGE_SEGMENTATION_MODE,
    }
    (output / "source.json").write_bytes(_canonical_json(source))
    matrix = {
        "include": [
            {"shard_index": index, "shard_count": shard_count}
            for index in range(shard_count)
        ]
    }
    (output / "matrix.json").write_bytes(_canonical_json(matrix))
    return {"source": source, "matrix": matrix}


def _page_text(page: Any) -> str:
    text_page = page.get_textpage()
    try:
        return text_page.get_text_range()
    finally:
        text_page.close()


def _render(page: Any) -> bytes:
    bitmap = page.render(scale=RENDER_SCALE)
    try:
        image = bitmap.to_pil()
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()
    finally:
        bitmap.close()


def _embedded_image_count(pdf_bytes: bytes, page_index: int) -> int | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
        return len(reader.pages[page_index].images)
    except Exception:
        return None


def _diff_segments(native_text: str, ocr_text: str) -> list[dict[str, Any]]:
    matcher = difflib.SequenceMatcher(a=native_text, b=ocr_text, autojunk=False)
    segments: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        native_start = max(0, i1 - DIFF_CONTEXT_CHARS)
        native_end = min(len(native_text), i2 + DIFF_CONTEXT_CHARS)
        ocr_start = max(0, j1 - DIFF_CONTEXT_CHARS)
        ocr_end = min(len(ocr_text), j2 + DIFF_CONTEXT_CHARS)
        segments.append(
            {
                "tag": tag,
                "native_span": [i1, i2],
                "ocr_span": [j1, j2],
                "native_excerpt": native_text[native_start:native_end],
                "ocr_excerpt": ocr_text[ocr_start:ocr_end],
            }
        )
        if len(segments) >= MAX_DIFF_SEGMENTS:
            break
    return segments


def _quality_route(
    *,
    classification: str,
    ocr: VisualOcrObservation,
    embedded_image_count: int | None,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if classification == "processing_error":
        return "blocked", ["processing_error"]
    if classification == "no_native_text":
        reasons.append("no_native_text")
        if embedded_image_count:
            reasons.append("embedded_images_present")
        return "visual_review", reasons
    if classification == "low_information":
        reasons.append("low_information")
        if embedded_image_count:
            reasons.append("embedded_images_present")
        return "visual_review" if embedded_image_count else "sentinel", reasons
    if classification == "misaligned":
        reasons.append("native_ocr_disagreement")
        if embedded_image_count:
            reasons.append("embedded_images_present")
        return "jev_review", reasons

    if ocr.p10_confidence is None:
        reasons.append("missing_confidence_tail")
    elif ocr.p10_confidence < STRONG_P10_CONFIDENCE:
        reasons.append("low_p10_ocr_confidence")
    if ocr.low_confidence_word_ratio is None:
        reasons.append("missing_low_confidence_ratio")
    elif ocr.low_confidence_word_ratio > STRONG_LOW_CONFIDENCE_WORD_RATIO:
        reasons.append("high_low_confidence_word_ratio")
    if reasons:
        return "sentinel", reasons
    return "accept_candidate", []


def _page_record(
    *,
    native_text: str,
    image: bytes,
    page_index: int,
    source_sha: str,
    embedded_image_count: int | None,
) -> dict[str, Any]:
    ocr = run_tesseract_visual_ocr(
        image,
        language=OCR_LANGUAGE,
        page_segmentation_mode=OCR_PAGE_SEGMENTATION_MODE,
    )
    native_chars = len(native_text.strip())
    ocr_chars = len(ocr.text.strip())
    if native_chars < LOW_INFORMATION_NATIVE_CHARS and ocr_chars < LOW_INFORMATION_OCR_CHARS:
        classification = "low_information"
        assessment: dict[str, Any] | None = None
    elif native_chars < LOW_INFORMATION_NATIVE_CHARS:
        classification = "no_native_text"
        assessment = None
    else:
        assessed = assess_visual_reference_alignment(
            native_text=native_text,
            ocr_text=ocr.text,
            ocr_mean_confidence=ocr.mean_confidence,
            policy=POLICY,
        )
        classification = "aligned" if assessed.accepted else "misaligned"
        assessment = assessed.to_json_dict()

    route, risk_reasons = _quality_route(
        classification=classification,
        ocr=ocr,
        embedded_image_count=embedded_image_count,
    )
    return {
        "schema_version": 1,
        "source_pdf_sha256": source_sha,
        "page_index": page_index,
        "classification": classification,
        "quality_route": route,
        "risk_reasons": risk_reasons,
        "native_characters": native_chars,
        "ocr_characters": ocr_chars,
        "native_text_sha256": _sha256(native_text.encode("utf-8")),
        "ocr_text_sha256": _sha256(ocr.text.encode("utf-8")),
        "render_sha256": _sha256(image),
        "ocr_engine": "tesseract",
        "ocr_engine_version": ocr.engine_version,
        "ocr_language": ocr.language,
        "ocr_page_segmentation_mode": OCR_PAGE_SEGMENTATION_MODE,
        "ocr_word_count": ocr.word_count,
        "ocr_mean_confidence": ocr.mean_confidence,
        "ocr_median_confidence": ocr.median_confidence,
        "ocr_p10_confidence": ocr.p10_confidence,
        "ocr_low_confidence_word_ratio": ocr.low_confidence_word_ratio,
        "embedded_image_count": embedded_image_count,
        "assessment": assessment,
        "diff_segments": (
            _diff_segments(native_text, ocr.text)
            if classification == "misaligned"
            else []
        ),
    }


def run_shard(
    *,
    source_pdf: Path,
    source_json: Path,
    shard_index: int,
    shard_count: int,
    output: Path,
) -> int:
    source = json.loads(source_json.read_text(encoding="utf-8"))
    expected_sha = str(source["source_pdf_sha256"])
    expected_pages = int(source["page_count"])
    expected_shards = int(source["shard_count"])
    if shard_count != expected_shards:
        raise RuntimeError("shard_count differs from frozen source metadata")
    if not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index")

    pdf_bytes = source_pdf.read_bytes()
    actual_sha = _sha256(pdf_bytes)
    if actual_sha != expected_sha:
        raise RuntimeError("source PDF checksum mismatch after fan-out")

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        if len(document) != expected_pages:
            raise RuntimeError("source PDF page count changed after fan-out")
        records: list[dict[str, Any]] = []
        for page_index in range(shard_index, expected_pages, shard_count):
            page = document[page_index]
            try:
                native_text = _page_text(page)
                image = _render(page)
            finally:
                page.close()
            record = _page_record(
                native_text=native_text,
                image=image,
                page_index=page_index,
                source_sha=actual_sha,
                embedded_image_count=_embedded_image_count(pdf_bytes, page_index),
            )
            record["shard_index"] = shard_index
            record["shard_count"] = shard_count
            records.append(record)
    finally:
        document.close()

    output.mkdir(parents=True, exist_ok=True)
    path = output / f"pages-{shard_index:02d}.jsonl"
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "source_pdf_sha256": actual_sha,
        "page_count": expected_pages,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "owned_pages": len(records),
        "page_counts": dict(Counter(str(item["classification"]) for item in records)),
        "route_counts": dict(Counter(str(item["quality_route"]) for item in records)),
    }
    (output / f"summary-{shard_index:02d}.json").write_bytes(_canonical_json(summary))
    return 0


def _load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                result.append(json.loads(line))
    return result


def aggregate(*, source_json: Path, input_root: Path, output: Path) -> int:
    source = json.loads(source_json.read_text(encoding="utf-8"))
    expected_sha = str(source["source_pdf_sha256"])
    expected_pages = int(source["page_count"])
    expected_shards = int(source["shard_count"])

    records = _load_jsonl(sorted(input_root.rglob("pages-*.jsonl")))
    if not records:
        raise RuntimeError("no shard page records found")
    shard_summaries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(input_root.rglob("summary-*.json"))
    ]
    observed_shards = {int(item["shard_index"]) for item in shard_summaries}
    if observed_shards != set(range(expected_shards)):
        raise RuntimeError("shard summaries do not cover the frozen shard plan")

    indices = [int(item["page_index"]) for item in records]
    duplicates = sorted(index for index, count in Counter(indices).items() if count > 1)
    missing = sorted(set(range(expected_pages)) - set(indices))
    unexpected = sorted(set(indices) - set(range(expected_pages)))
    bad_sha = [item for item in records if str(item["source_pdf_sha256"]) != expected_sha]
    if duplicates or missing or unexpected or bad_sha:
        raise RuntimeError(
            "page reconciliation failed: "
            f"duplicates={len(duplicates)} missing={len(missing)} "
            f"unexpected={len(unexpected)} bad_sha={len(bad_sha)}"
        )

    records.sort(key=lambda item: int(item["page_index"]))
    output.mkdir(parents=True, exist_ok=True)
    (output / "pages.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )

    jev = [
        item for item in records
        if item["quality_route"] in {"jev_review", "sentinel"}
    ]
    visual = [
        item for item in records
        if item["quality_route"] == "visual_review"
        or (
            item["classification"] == "misaligned"
            and int(item.get("embedded_image_count") or 0) > 0
        )
    ]
    for name, items in (("jev-review.jsonl", jev), ("visual-review.jsonl", visual)):
        (output / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items),
            encoding="utf-8",
        )

    p10_values = [
        float(item["ocr_p10_confidence"])
        for item in records
        if item.get("ocr_p10_confidence") is not None
    ]
    summary = {
        "schema_version": 1,
        "object_key": source["object_key"],
        "source_pdf_sha256": expected_sha,
        "total_pages": expected_pages,
        "shard_count": expected_shards,
        "complete_scan": len(records) == expected_pages,
        "page_counts": dict(Counter(str(item["classification"]) for item in records)),
        "route_counts": dict(Counter(str(item["quality_route"]) for item in records)),
        "jev_review_pages": len(jev),
        "visual_review_pages": len(visual),
        "ocr_p10_confidence_median": statistics.median(p10_values) if p10_values else None,
        "heuristic_policy": {
            "strong_p10_confidence": STRONG_P10_CONFIDENCE,
            "strong_low_confidence_word_ratio": STRONG_LOW_CONFIDENCE_WORD_RATIO,
            "note": (
                "Benchmark routing heuristics only; they do not promote text into "
                "canonical legal evidence without the existing admission policy."
            ),
        },
        "alignment_policy": {
            name: getattr(POLICY, name)
            for name in POLICY.__dataclass_fields__
        },
    }
    (output / "summary.json").write_bytes(_canonical_json(summary))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--object-key", required=True)
    prepare.add_argument("--shard-count", type=int, default=20)
    prepare.add_argument("--output", type=Path, required=True)

    shard = subparsers.add_parser("shard")
    shard.add_argument("--source-pdf", type=Path, required=True)
    shard.add_argument("--source-json", type=Path, required=True)
    shard.add_argument("--shard-index", type=int, required=True)
    shard.add_argument("--shard-count", type=int, required=True)
    shard.add_argument("--output", type=Path, required=True)

    combine = subparsers.add_parser("aggregate")
    combine.add_argument("--source-json", type=Path, required=True)
    combine.add_argument("--input-root", type=Path, required=True)
    combine.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_source(
            object_key=args.object_key,
            output=args.output,
            shard_count=args.shard_count,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "shard":
        return run_shard(
            source_pdf=args.source_pdf,
            source_json=args.source_json,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            output=args.output,
        )
    return aggregate(
        source_json=args.source_json,
        input_root=args.input_root,
        output=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
