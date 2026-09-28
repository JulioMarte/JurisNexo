from __future__ import annotations

"""Exhaustively verify SCJ Principales native text against independent OCR.

The primary execution unit is one immutable PDF. Per-document artifacts retain
page-level provenance, admitted native text, verification metrics, and verified
contiguous runs. Legacy shard mode remains for local/backward-compatible use.
"""

import argparse
import hashlib
import io
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
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)
from jurisnexo.normalization.visual_reference_ocr import run_tesseract_visual_ocr

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
POLICY = VisualReferencePolicy()
LOW_INFORMATION_NATIVE_CHARS = 80
LOW_INFORMATION_OCR_CHARS = 80
RENDER_SCALE = 2.0
OCR_LANGUAGE = "spa+eng"
OCR_PAGE_SEGMENTATION_MODE = 6
_STOP = False


class SourceIdentityDriftError(RuntimeError):
    """The downloaded object no longer matches the frozen inventory."""


def _request_stop(signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    print(
        f"\nReceived signal {signum}; finishing current page and checkpointing...",
        file=sys.stderr,
        flush=True,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list_pdf_keys(store: Any) -> list[str]:
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
        keys.extend(
            str(item.get("Key") or "")
            for item in response.get("Contents", [])
            if str(item.get("Key") or "").endswith(".pdf")
        )
        if not response.get("IsTruncated"):
            return sorted(set(keys))
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("S3 listing truncated without continuation token")


def _normalized_etag(value: object) -> str:
    return str(value or "").strip().strip('"')


def _cache_path(cache_dir: Path, key: str, expected_etag: str | None) -> Path:
    identity = expected_etag or "unversioned"
    digest = hashlib.sha256(f"{key}\0{identity}".encode()).hexdigest()
    return cache_dir / f"{digest}-{Path(key).name}"


def _read_pdf(
    store: Any,
    key: str,
    cache_dir: Path | None = None,
    *,
    expected_size: int | None = None,
    expected_etag: str | None = None,
) -> bytes:
    path: Path | None = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(cache_dir, key, expected_etag)
        if path.exists():
            data = path.read_bytes()
            if expected_size is not None and len(data) != expected_size:
                path.unlink()
            else:
                return data

    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = store.client.get_object(
                Bucket=store.config.bucket,
                Key=key,
            )
            body = response["Body"].read()
            data = body if isinstance(body, bytes) else bytes(body)
            actual_size = int(response.get("ContentLength") or len(data))
            actual_etag = _normalized_etag(response.get("ETag"))

            if expected_size is not None and actual_size != expected_size:
                raise SourceIdentityDriftError(
                    f"source object size drift for {key}: "
                    f"expected {expected_size}, got {actual_size}"
                )
            if expected_size is not None and len(data) != expected_size:
                raise SourceIdentityDriftError(
                    f"downloaded byte count drift for {key}: "
                    f"expected {expected_size}, got {len(data)}"
                )
            if expected_etag and actual_etag != expected_etag:
                raise SourceIdentityDriftError(
                    f"source object ETag drift for {key}: "
                    f"expected {expected_etag}, got {actual_etag or '<missing>'}"
                )

            if path is not None:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, path)
            return data
        except SourceIdentityDriftError:
            raise
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
    bitmap = page.render(scale=RENDER_SCALE)
    try:
        image = bitmap.to_pil()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        bitmap.close()


def classify_page(
    *,
    native_text: str,
    image: bytes,
    include_ocr_text: bool = False,
) -> dict[str, Any]:
    ocr = run_tesseract_visual_ocr(
        image,
        language=OCR_LANGUAGE,
        page_segmentation_mode=OCR_PAGE_SEGMENTATION_MODE,
    )
    native_chars = len(native_text.strip())
    ocr_chars = len(ocr.text.strip())
    base = {
        "native_characters": native_chars,
        "ocr_characters": ocr_chars,
        "ocr_mean_confidence": ocr.mean_confidence,
        "ocr_engine_version": ocr.engine_version,
        "ocr_language": ocr.language,
        "ocr_page_segmentation_mode": OCR_PAGE_SEGMENTATION_MODE,
        "native_text_sha256": _sha256(native_text.encode("utf-8")),
        "ocr_text_sha256": _sha256(ocr.text.encode("utf-8")),
    }
    if include_ocr_text:
        base["ocr_text"] = ocr.text
    if (
        native_chars < LOW_INFORMATION_NATIVE_CHARS
        and ocr_chars < LOW_INFORMATION_OCR_CHARS
    ):
        return {"classification": "low_information", **base}
    if (
        native_chars < LOW_INFORMATION_NATIVE_CHARS
        and ocr_chars >= LOW_INFORMATION_OCR_CHARS
    ):
        return {"classification": "no_native_text", **base}

    assessment = assess_visual_reference_alignment(
        native_text=native_text,
        ocr_text=ocr.text,
        ocr_mean_confidence=ocr.mean_confidence,
        policy=POLICY,
    )
    return {
        "classification": "aligned" if assessment.accepted else "misaligned",
        **base,
        "assessment": assessment.to_json_dict(),
    }


def _load_completed(
    records_path: Path,
) -> tuple[set[tuple[str, int]], Counter[str]]:
    completed: set[tuple[str, int]] = set()
    counts: Counter[str] = Counter()
    if not records_path.exists():
        return completed, counts

    with records_path.open(encoding="utf-8") as source:
        lines = source.readlines()

    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if line_no != len(lines):
                raise RuntimeError(f"corrupt checkpoint at line {line_no}")
            break
        classification = str(record.get("classification") or "")
        if classification:
            counts[classification] += 1
        if record.get("scope") != "document" and "page_index" in record:
            completed.add(
                (str(record["object_key"]), int(record["page_index"]))
            )
    return completed, counts


def _page_runs(
    records: list[dict[str, Any]],
    classifications: set[str],
) -> list[dict[str, int]]:
    selected = sorted(
        int(record["page_index"])
        for record in records
        if str(record.get("classification") or "") in classifications
    )
    if not selected:
        return []

    runs: list[dict[str, int]] = []
    start = previous = selected[0]
    for page_index in selected[1:]:
        if page_index != previous + 1:
            runs.append(
                {
                    "start_page_index": start,
                    "end_page_index": previous,
                    "page_count": previous - start + 1,
                }
            )
            start = page_index
        previous = page_index

    runs.append(
        {
            "start_page_index": start,
            "end_page_index": previous,
            "page_count": previous - start + 1,
        }
    )
    return runs


def _verified_runs(records: list[dict[str, Any]]) -> list[dict[str, int]]:
    return _page_runs(records, {"aligned"})


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _document_summary(
    *,
    key: str,
    pdf_sha: str,
    source_page_count: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = Counter(
        str(record.get("classification") or "")
        for record in records
    )
    processed_pages = len(records)
    relevant = (
        processed_pages
        - counts["low_information"]
        - counts["processing_error"]
    )
    aligned = counts["aligned"]
    ratio = aligned / relevant if relevant else 0.0
    verified_share = (
        aligned / source_page_count
        if source_page_count
        else 0.0
    )

    score_rows = [
        record["assessment"]["score"]
        for record in records
        if isinstance(record.get("assessment"), dict)
        and isinstance(record["assessment"].get("score"), dict)
    ]
    wers = [float(score["word_error_rate"]) for score in score_rows]
    cers = [float(score["character_error_rate"]) for score in score_rows]
    critical_recalls = [
        float(score["legal_critical_recall"]) for score in score_rows
    ]
    critical_failures = sum(value < 1.0 for value in critical_recalls)

    observed_page_indices = {
        int(record["page_index"])
        for record in records
        if "page_index" in record
    }
    expected_page_indices = set(range(source_page_count))
    complete_scan = (
        source_page_count > 0
        and processed_pages == source_page_count
        and observed_page_indices == expected_page_indices
    )
    if (
        complete_scan
        and counts["processing_error"] == 0
        and aligned == source_page_count
    ):
        tier = "verified_complete"
    elif (
        complete_scan
        and counts["processing_error"] == 0
        and critical_failures == 0
        and verified_share >= 0.995
    ):
        tier = "verified_near_complete"
    elif (
        complete_scan
        and counts["processing_error"] == 0
        and verified_share >= 0.95
    ):
        tier = "verified_partial"
    else:
        tier = "unsuitable"

    verified_runs = _verified_runs(records)
    problem_runs = _page_runs(
        records,
        {"misaligned", "no_native_text", "processing_error"},
    )
    policy = {
        name: getattr(POLICY, name)
        for name in POLICY.__dataclass_fields__
    }
    policy_sha256 = _sha256(
        json.dumps(
            policy,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    ocr_engine_versions = sorted(
        {
            str(record["ocr_engine_version"])
            for record in records
            if record.get("ocr_engine_version")
        }
    )

    return {
        "schema_version": 5,
        "object_key": key,
        "source_pdf_sha256": pdf_sha,
        "source_page_count": source_page_count,
        "processed_pages": processed_pages,
        "complete_scan": complete_scan,
        "page_counts": dict(sorted(counts.items())),
        "relevant_pages": relevant,
        "aligned_share_of_relevant": ratio,
        "verified_share_of_all_pages": verified_share,
        "verification_tier": tier,
        "critical_alignment_failures": critical_failures,
        "worst_word_error_rate": max(wers, default=None),
        "p95_word_error_rate": _percentile(wers, 0.95),
        "worst_character_error_rate": max(cers, default=None),
        "p95_character_error_rate": _percentile(cers, 0.95),
        "minimum_legal_critical_recall": min(
            critical_recalls,
            default=None,
        ),
        "verified_runs": verified_runs,
        "longest_verified_run_pages": max(
            (run["page_count"] for run in verified_runs),
            default=0,
        ),
        "longest_problem_run_pages": max(
            (run["page_count"] for run in problem_runs),
            default=0,
        ),
        "render_scale": RENDER_SCALE,
        "ocr_language": OCR_LANGUAGE,
        "ocr_page_segmentation_mode": OCR_PAGE_SEGMENTATION_MODE,
        "ocr_engine_versions": ocr_engine_versions,
        "policy": policy,
        "policy_sha256": policy_sha256,
        "code_revision": (
            os.environ.get("SCJ_CODE_REVISION")
            or os.environ.get("GITHUB_SHA")
        ),
    }


def run_document(
    *,
    object_key: str,
    output: Path,
    cache_dir: Path | None = None,
    progress_every: int = 25,
    expected_size: int | None = None,
    expected_etag: str | None = None,
) -> int:
    output.mkdir(parents=True, exist_ok=True)
    store = build_s3_object_store()
    pdf_bytes = _read_pdf(
        store,
        object_key,
        cache_dir,
        expected_size=expected_size,
        expected_etag=expected_etag,
    )
    pdf_sha = _sha256(pdf_bytes)
    document = pdfium.PdfDocument(pdf_bytes)
    source_page_count = len(document)
    records: list[dict[str, Any]] = []
    started = time.monotonic()

    try:
        for page_index in range(source_page_count):
            if _STOP:
                break
            try:
                page = document[page_index]
                try:
                    native_text = _page_text(page)
                    image = _render(page)
                    image_sha = _sha256(image)
                finally:
                    page.close()
                result = classify_page(
                    native_text=native_text,
                    image=image,
                    include_ocr_text=True,
                )
                ocr_text = str(result.pop("ocr_text"))
                observation_native = output / "observations" / "native"
                observation_ocr = output / "observations" / "ocr"
                observation_native.mkdir(parents=True, exist_ok=True)
                observation_ocr.mkdir(parents=True, exist_ok=True)
                (observation_native / f"page-{page_index:05d}.txt").write_text(
                    native_text,
                    encoding="utf-8",
                )
                (observation_ocr / f"page-{page_index:05d}.txt").write_text(
                    ocr_text,
                    encoding="utf-8",
                )
                if result["classification"] == "aligned":
                    text_dir = output / "reference-text"
                    text_dir.mkdir(exist_ok=True)
                    (text_dir / f"page-{page_index:05d}.txt").write_text(
                        native_text,
                        encoding="utf-8",
                    )
            except Exception as exc:
                image_sha = None
                result = {
                    "classification": "processing_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            record = {
                "object_key": object_key,
                "source_pdf_sha256": pdf_sha,
                "page_index": page_index,
                "render_sha256": image_sha,
                **result,
            }
            records.append(record)

            if len(records) % max(progress_every, 1) == 0:
                elapsed = max(
                    time.monotonic() - started,
                    0.001,
                )
                print(
                    f"{Path(object_key).name}: "
                    f"{len(records)}/{source_page_count} pages "
                    f"({len(records) / elapsed:.2f} pages/s)",
                    flush=True,
                )
    finally:
        document.close()

    records_path = output / "pages.jsonl"
    records_path.write_text(
        "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )

    summary = _document_summary(
        key=object_key,
        pdf_sha=pdf_sha,
        source_page_count=source_page_count,
        records=records,
    )
    summary["interrupted"] = _STOP
    summary["expected_size_bytes"] = expected_size
    summary["expected_etag"] = expected_etag
    (output / "document.json").write_text(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))

    if _STOP:
        return 130
    if not summary["complete_scan"]:
        return 2
    return (
        0
        if summary["page_counts"].get("processing_error", 0) == 0
        else 2
    )


def aggregate(
    *,
    input_root: Path,
    output: Path,
    inventory_path: Path | None = None,
) -> int:
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(input_root.rglob("document.json"))
    ]
    if not documents:
        raise RuntimeError("no document summaries found")

    documents.sort(
        key=lambda item: (
            -float(item["verified_share_of_all_pages"]),
            -int(item["longest_verified_run_pages"]),
            str(item["object_key"]),
        )
    )

    expected_keys: set[str] = set()
    inventory_sha256: str | None = None
    if inventory_path is not None:
        inventory = json.loads(
            inventory_path.read_text(encoding="utf-8")
        )
        expected_keys = {
            str(item["object_key"])
            for item in inventory["documents"]
        }
        inventory_sha256 = str(inventory["inventory_sha256"])

    observed_keys = {
        str(document["object_key"])
        for document in documents
    }
    missing_documents = sorted(expected_keys - observed_keys)
    unexpected_documents = sorted(observed_keys - expected_keys)

    counts: Counter[str] = Counter()
    for document in documents:
        counts.update(document["page_counts"])

    total = sum(counts.values())
    relevant = (
        total
        - counts["low_information"]
        - counts["processing_error"]
    )
    incomplete_documents = sorted(
        str(item["object_key"])
        for item in documents
        if not item.get("complete_scan")
        or item.get("interrupted")
    )

    report = {
        "schema_version": 5,
        "inventory_sha256": inventory_sha256,
        "expected_documents": (
            len(expected_keys) if expected_keys else None
        ),
        "documents": len(documents),
        "missing_documents": missing_documents,
        "unexpected_documents": unexpected_documents,
        "incomplete_documents": incomplete_documents,
        "total_pages": total,
        "page_counts": dict(sorted(counts.items())),
        "relevant_pages": relevant,
        "aligned_share_of_relevant": (
            counts["aligned"] / relevant
            if relevant
            else 0.0
        ),
        "verified_share_of_all_pages": (
            counts["aligned"] / total
            if total
            else 0.0
        ),
        "verification_tiers": dict(
            Counter(
                str(item["verification_tier"])
                for item in documents
            )
        ),
        "document_ranking": documents,
    }

    output.mkdir(parents=True, exist_ok=True)
    (output / "census-summary.json").write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    invalid = bool(
        counts["processing_error"]
        or missing_documents
        or unexpected_documents
        or incomplete_documents
    )
    return 2 if invalid else 0


def run_legacy_shard(
    *,
    shard_index: int,
    shard_count: int,
    output: Path,
    cache_dir: Path | None = None,
) -> int:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard")

    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    owned = [
        key
        for index, key in enumerate(keys)
        if index % shard_count == shard_index
    ]
    statuses = [
        run_document(
            object_key=key,
            output=output / f"document-{index:03d}",
            cache_dir=cache_dir,
        )
        for index, key in enumerate(owned)
    ]
    return max(statuses, default=0)


def main() -> int:
    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("--object-key")
    parser.add_argument("--expected-size", type=int)
    parser.add_argument("--expected-etag")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    if args.aggregate:
        if args.input_root is None:
            parser.error("--input-root is required with --aggregate")
        return aggregate(
            input_root=args.input_root,
            output=args.output,
            inventory_path=args.inventory,
        )

    if args.object_key:
        return run_document(
            object_key=args.object_key,
            output=args.output,
            cache_dir=args.cache_dir,
            progress_every=args.progress_every,
            expected_size=args.expected_size,
            expected_etag=args.expected_etag,
        )

    return run_legacy_shard(
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        output=args.output,
        cache_dir=args.cache_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
