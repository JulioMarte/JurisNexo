from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from principales_corpus_suite import CHECKPOINT_PREFIX, _download
from scj_page_selection import (
    FRONT_MATTER_MARKERS,
    looks_like_body_page,
    normalize_native_reference,
)

SOURCE_RUN = "github-35940805815-attempt-1"
EXPECTED_INVENTORY_SHA256 = (
    "31de3eb9e72b66001f329e859c8b45d434c40a58e9c8ee21f21721c7a8ea7023"
)
OUTPUT = Path(os.environ["SELECTOR_AUDIT_OUTPUT"])


def _scan_all_pages(source: bytes) -> dict[str, object]:
    document = pdfium.PdfDocument(source)
    try:
        native_pages = 0
        long_native_pages = 0
        qualifying_pages = 0
        first_qualifying_page: int | None = None
        pages_with_body_markers = 0
        pages_with_body_and_front_markers = 0
        front_marker_page_counts = {marker: 0 for marker in FRONT_MATTER_MARKERS}
        examples: list[dict[str, object]] = []
        for index in range(len(document)):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    reference = normalize_native_reference(
                        text_page.get_text_range()
                    )
                finally:
                    text_page.close()
            finally:
                page.close()
            if len(reference) >= 200:
                native_pages += 1
            if len(reference) >= 800:
                long_native_pages += 1
                folded = reference.casefold()
                body_markers = [
                    marker
                    for marker, present in (
                        ("considerando_twice", folded.count("considerando") >= 2),
                        ("en_nombre", "en nombre de la república" in folded),
                        (
                            "vistos_falla",
                            "vistos" in folded
                            and ("falla" in folded or "fallamos" in folded),
                        ),
                    )
                    if present
                ]
                front_markers = [
                    marker for marker in FRONT_MATTER_MARKERS if marker in folded
                ]
                for marker in front_markers:
                    front_marker_page_counts[marker] += 1
                if body_markers:
                    pages_with_body_markers += 1
                    if front_markers:
                        pages_with_body_and_front_markers += 1
                capture_example = index in {
                    0,
                    min(len(document) - 1, 20),
                    len(document) // 2,
                } or (body_markers and len(examples) < 4)
                if capture_example and len(examples) < 7:
                    examples.append(
                        {
                            "page_index": index,
                            "body_markers": body_markers,
                            "front_markers": front_markers,
                            "sample_text": reference[:700],
                        }
                    )
                if looks_like_body_page(reference):
                    qualifying_pages += 1
                    if first_qualifying_page is None:
                        first_qualifying_page = index
        return {
            "page_count": len(document),
            "native_pages_at_least_200_chars": native_pages,
            "native_pages_at_least_800_chars": long_native_pages,
            "qualifying_body_pages": qualifying_pages,
            "first_qualifying_page_index": first_qualifying_page,
            "pages_with_body_markers_before_front_rejection": pages_with_body_markers,
            "pages_with_body_and_front_markers": pages_with_body_and_front_markers,
            "front_marker_page_counts": front_marker_page_counts,
            "examples": examples,
        }
    finally:
        document.close()


def main() -> int:
    store = build_s3_object_store()
    report_key = f"{CHECKPOINT_PREFIX}runs/{SOURCE_RUN}/report.json"
    raw = store.client.get_object(
        Bucket=store.config.bucket, Key=report_key
    )["Body"].read()
    report: dict[str, Any] = json.loads(raw)
    if report["inventory_sha256"] != EXPECTED_INVENTORY_SHA256:
        raise RuntimeError("source inventory digest differs from frozen run")
    results: list[dict[str, object]] = []
    for item in report["coverage"]:
        if item["status"] not in {
            "no_reference_pages",
            "no_reference_pages_in_scan_window",
        }:
            continue
        key = str(item["object_key"])
        sha = str(item["source_sha256"])
        source = _download(store, key)
        if hashlib.sha256(source).hexdigest() != sha:
            raise RuntimeError(f"source checksum mismatch for {key}")
        results.append(
            {
                "object_key": key,
                "source_sha256": sha,
                **_scan_all_pages(source),
            }
        )
    if len(results) != 12:
        raise RuntimeError(f"expected 12 excluded volumes, found {len(results)}")
    payload = {
        "source_run": SOURCE_RUN,
        "inventory_sha256": EXPECTED_INVENTORY_SHA256,
        "selector_scan_limit_in_source_run": report["max_pages_to_scan"]
        if "max_pages_to_scan" in report
        else 120,
        "results": results,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "selector-audit.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
