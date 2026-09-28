from __future__ import annotations

"""Exhaustively classify SCJ Principales PDF pages without paid LLM calls.

Designed for both GitHub Actions and long-running local execution. Results are
append-only JSONL, PDFs can be cached locally, completed pages are skipped on
resume, and SIGINT/CTRL+C leaves a valid checkpoint that can be resumed.
"""

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.visual_reference_alignment import VisualReferencePolicy, assess_visual_reference_alignment
from jurisnexo.normalization.visual_reference_ocr import run_tesseract_visual_ocr

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
POLICY = VisualReferencePolicy()
LOW_INFORMATION_NATIVE_CHARS = 80
LOW_INFORMATION_OCR_CHARS = 80
_STOP = False


def _request_stop(signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    print(f"\nReceived signal {signum}; finishing current page and checkpointing...", file=sys.stderr, flush=True)


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


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}-{Path(key).name}"


def _read_pdf(store: Any, key: str, cache_dir: Path | None = None) -> bytes:
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(cache_dir, key)
        if path.exists():
            return path.read_bytes()
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            body = store.client.get_object(Bucket=store.config.bucket, Key=key)["Body"].read()
            data = body if isinstance(body, bytes) else bytes(body)
            if cache_dir is not None:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, path)
            return data
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    assert last is not None
    raise last


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
    return {"classification": "aligned" if assessment.accepted else "misaligned", "native_characters": native_chars, "ocr_characters": ocr_chars, "ocr_mean_confidence": ocr.mean_confidence, "assessment": assessment.to_json_dict()}


def _load_completed(records_path: Path) -> tuple[set[tuple[str, int]], Counter[str]]:
    completed: set[tuple[str, int]] = set()
    counts: Counter[str] = Counter()
    if not records_path.exists():
        return completed, counts
    with records_path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # Only tolerate a torn final append from an interrupted process.
                if source.read(1):
                    raise RuntimeError(f"corrupt checkpoint at line {line_no}")
                break
            classification = str(record.get("classification") or "")
            if classification:
                counts[classification] += 1
            if record.get("scope") != "document" and "page_index" in record:
                completed.add((str(record["object_key"]), int(record["page_index"])))
    return completed, counts


def _write_summary(output: Path, shard_index: int, shard_count: int, keys: list[str], owned: list[str], counts: Counter[str], interrupted: bool) -> None:
    summary = {"schema_version": 2, "shard_index": shard_index, "shard_count": shard_count, "pdf_objects_total": len(keys), "pdf_objects_owned": len(owned), "page_counts": dict(sorted(counts.items())), "pages_processed": sum(counts.values()), "interrupted": interrupted, "policy": {name: getattr(POLICY, name) for name in POLICY.__dataclass_fields__}}
    (output / f"summary-{shard_index:03d}.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(*, shard_index: int, shard_count: int, output: Path, resume: bool = False, cache_dir: Path | None = None, progress_every: int = 25) -> int:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard")
    output.mkdir(parents=True, exist_ok=True)
    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    owned = [key for index, key in enumerate(keys) if index % shard_count == shard_index]
    records_path = output / f"pages-{shard_index:03d}.jsonl"
    if records_path.exists() and not resume:
        raise RuntimeError(f"{records_path} already exists; pass --resume or choose another --output")
    completed, counts = _load_completed(records_path) if resume else (set(), Counter())
    started = time.monotonic()
    newly_processed = 0
    print(f"SCJ census: {len(keys)} PDFs total; worker owns {len(owned)}; resuming {len(completed)} completed pages", flush=True)
    with records_path.open("a", encoding="utf-8", buffering=1) as sink:
        for key in owned:
            if _STOP:
                break
            try:
                pdf_bytes = _read_pdf(store, key, cache_dir)
                document = pdfium.PdfDocument(pdf_bytes)
            except Exception as exc:
                marker = (key, -1)
                if marker not in completed:
                    counts["processing_error"] += 1
                    sink.write(json.dumps({"object_key": key, "classification": "processing_error", "scope": "document", "error": f"{type(exc).__name__}: {exc}"}) + "\n")
                continue
            try:
                pdf_sha = _sha256(pdf_bytes)
                for page_index in range(len(document)):
                    if _STOP:
                        break
                    if (key, page_index) in completed:
                        continue
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
                    completed.add((key, page_index))
                    newly_processed += 1
                    if newly_processed % max(progress_every, 1) == 0:
                        elapsed = max(time.monotonic() - started, 0.001)
                        rate = newly_processed / elapsed
                        print(f"processed={len(completed)} new={newly_processed} rate={rate:.2f} pages/s aligned={counts['aligned']} misaligned={counts['misaligned']} no_native={counts['no_native_text']} low_info={counts['low_information']} errors={counts['processing_error']}", flush=True)
            finally:
                document.close()
    _write_summary(output, shard_index, shard_count, keys, owned, counts, _STOP)
    print(json.dumps({"pages_processed": sum(counts.values()), "newly_processed": newly_processed, "interrupted": _STOP, "page_counts": dict(counts)}, sort_keys=True), flush=True)
    if _STOP:
        return 130
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
    report = {"schema_version": 2, "shards": len(summaries), "total_pages": total, "page_counts": dict(sorted(counts.items())), "relevant_pages": relevant, "aligned_share_of_relevant": counts["aligned"] / relevant if relevant else 0.0, "pages_needing_normalization": needs_normalization, "normalization_share_of_relevant": needs_normalization / relevant if relevant else 0.0, "processing_errors": counts["processing_error"], "interrupted_shards": sum(bool(x.get("interrupted")) for x in summaries)}
    output.mkdir(parents=True, exist_ok=True)
    (output / "census-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if counts["processing_error"] == 0 and not report["interrupted_shards"] else 2


def main() -> int:
    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Resume from append-only JSONL checkpoint")
    parser.add_argument("--cache-dir", type=Path, help="Cache downloaded source PDFs locally")
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    if args.aggregate:
        if args.input_root is None:
            parser.error("--input-root is required with --aggregate")
        return aggregate(input_root=args.input_root, output=args.output)
    return run(shard_index=args.shard_index, shard_count=args.shard_count, output=args.output, resume=args.resume, cache_dir=args.cache_dir, progress_every=args.progress_every)


if __name__ == "__main__":
    raise SystemExit(main())
