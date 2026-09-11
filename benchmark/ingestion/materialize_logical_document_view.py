from __future__ import annotations

import argparse
import json
from pathlib import Path

from jurisnexo.ingestion.logical_document_view import materialize_logical_document_view
from jurisnexo.ingestion.scanned_page_materialization import (
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
    sanitize_bbox_layout_xml,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize deduplicated logical document view")
    parser.add_argument("--bbox", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-region-characters", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    raw_xml = args.bbox.read_text(encoding="utf-8", errors="replace")
    _, replacement_count = sanitize_bbox_layout_xml(raw_xml)
    physical_pages = parse_bbox_layout(raw_xml)
    duplicate_scans = detect_adjacent_duplicate_scans(physical_pages)
    view = materialize_logical_document_view(
        physical_pages=physical_pages,
        duplicate_scans=duplicate_scans,
        minimum_region_characters=args.minimum_region_characters,
    )

    payload = {
        "physical_page_count": len(physical_pages),
        "duplicate_scan_count": len(duplicate_scans),
        "scan_group_count": view.scan_group_count,
        "logical_view_page_count": len(view.pages),
        "xml_forbidden_control_character_count": replacement_count,
        "dominant_printed_page_offset": view.dominant_printed_page_offset,
        "dominant_offset_support": view.dominant_offset_support,
        "pages_with_printed_candidates": view.pages_with_printed_candidates,
        "resolved_printed_page_count": view.resolved_printed_page_count,
        "pages": [
            {
                "view_page_number": page.view_page_number,
                "side": page.side,
                "source_physical_pages": list(page.source_physical_pages),
                "representative_physical_page": page.representative_physical_page,
                "printed_page_candidates": list(page.printed_page_candidates),
                "resolved_printed_page": page.resolved_printed_page,
                "printed_page_resolution_method": page.printed_page_resolution_method,
                "text": page.text,
            }
            for page in view.pages
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {key: value for key, value in payload.items() if key != "pages"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
