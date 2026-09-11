from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from jurisnexo.ingestion.scanned_page_materialization import (
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze scanned PDF bbox layout")
    parser.add_argument("--bbox", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duplicate-threshold", type=float, default=0.70)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    layouts = parse_bbox_layout(args.bbox.read_text(encoding="utf-8", errors="replace"))
    duplicates = detect_adjacent_duplicate_scans(
        layouts,
        minimum_token_jaccard=args.duplicate_threshold,
    )

    printed_region_count = sum(
        1
        for page in layouts
        for region in page.regions
        if region.printed_page_candidates
    )
    pages_with_two_printed_candidates = sum(
        1 for page in layouts if len(page.printed_page_candidates) >= 2
    )
    payload = {
        "physical_page_count": len(layouts),
        "logical_region_count": sum(len(page.regions) for page in layouts),
        "regions_with_printed_page_candidates": printed_region_count,
        "physical_pages_with_two_or_more_printed_page_candidates": pages_with_two_printed_candidates,
        "adjacent_duplicate_scan_count": len(duplicates),
        "adjacent_duplicate_scans": [asdict(item) for item in duplicates],
        "pages": [
            {
                "physical_page_number": page.physical_page_number,
                "width": page.width,
                "height": page.height,
                "printed_page_candidates": list(page.printed_page_candidates),
                "regions": [
                    {
                        "side": region.side,
                        "x_min": region.x_min,
                        "x_max": region.x_max,
                        "printed_page_candidates": list(region.printed_page_candidates),
                        "text_character_count": len(region.text),
                    }
                    for region in page.regions
                ],
            }
            for page in layouts
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in payload.items() if key != "pages"}, indent=2))


if __name__ == "__main__":
    main()
