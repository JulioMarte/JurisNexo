from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.gold import assess_reference_text_health

from scj_principales_visual_corpus_benchmark import (
    PREFIX,
    _download,
    _list_pdf_keys,
    _native_text,
    _page_count,
    _render_page,
)

PAGE_COUNT = int(os.environ.get("SCJ_VISUAL_PAGE_COUNT", "100"))
SEED = os.environ.get("SCJ_VISUAL_CORPUS_SEED", "jurisnexo-principales-visual-v1")
MANIFEST = Path(os.environ.get("SCJ_VISUAL_CORPUS_MANIFEST", "scj-visual-corpus-manifest.json"))
MAX_PAGES_PER_PDF_TO_SCAN = int(os.environ.get("SCJ_VISUAL_MAX_PAGES_PER_PDF_TO_SCAN", "120"))


def _eligible_pages(source: bytes, rng: random.Random) -> list[tuple[int, str]]:
    count = _page_count(source)
    indexes = list(range(count))
    rng.shuffle(indexes)
    eligible: list[tuple[int, str]] = []
    for page_index in indexes[: min(count, MAX_PAGES_PER_PDF_TO_SCAN)]:
        try:
            text = _native_text(source, page_index)
        except Exception:
            continue
        if len(text.strip()) < 800:
            continue
        if not assess_reference_text_health(text).is_reliable:
            continue
        eligible.append((page_index, text))
    return eligible


def main() -> int:
    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    rng = random.Random(SEED)
    rng.shuffle(keys)

    # Build a deterministic pool first. The previous implementation selected at
    # most one page per PDF, which accidentally capped this corpus at 36 pages.
    # We still maximize document diversity by selecting in round-robin passes:
    # first eligible page from every PDF, then the second, and so on.
    pools: list[tuple[str, list[tuple[int, str]]]] = []
    eligible_total = 0
    for key in keys:
        try:
            source = _download(store, key)
            pages = _eligible_pages(source, rng)
        except Exception:
            continue
        if not pages:
            continue
        pools.append((key, pages))
        eligible_total += len(pages)

    if eligible_total < PAGE_COUNT:
        raise RuntimeError(
            f"needed {PAGE_COUNT} eligible pages, found {eligible_total} "
            f"across {len(pools)} PDFs under {PREFIX}"
        )

    chosen: list[tuple[str, int, str]] = []
    depth = 0
    while len(chosen) < PAGE_COUNT:
        added = False
        for key, pages in pools:
            if depth >= len(pages):
                continue
            page_index, text = pages[depth]
            chosen.append((key, page_index, text))
            added = True
            if len(chosen) == PAGE_COUNT:
                break
        if not added:
            break
        depth += 1

    if len(chosen) != PAGE_COUNT:
        raise RuntimeError(f"round-robin selection produced {len(chosen)} of {PAGE_COUNT} pages")

    samples: list[dict[str, Any]] = []
    cached_key = ""
    cached_source = b""
    for key, page_index, text in chosen:
        if key != cached_key:
            cached_source = _download(store, key)
            cached_key = key
        image = _render_page(cached_source, page_index)
        samples.append(
            {
                "sample_id": f"{hashlib.sha256(key.encode()).hexdigest()[:12]}-p{page_index + 1}",
                "object_key": key,
                "page_index": page_index,
                "reference_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "reference_characters": len(text),
            }
        )

    payload = {
        "schema_version": 1,
        "seed": SEED,
        "page_count": PAGE_COUNT,
        "selection": (
            "deterministic pseudo-random reliable born-digital body pages, "
            "round-robin across distinct PDFs to maximize source diversity"
        ),
        "source_pdf_count": len({sample["object_key"] for sample in samples}),
        "eligible_pdf_count": len(pools),
        "eligible_page_count": eligible_total,
        "samples": samples,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest_pages": len(samples),
                "source_pdfs": payload["source_pdf_count"],
                "eligible_pages": eligible_total,
                "seed": SEED,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
