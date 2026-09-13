from __future__ import annotations

import pytest

from jurisnexo.ingestion.artifact_inspection import (
    build_artifact_inspection_profile,
    parse_pdfimages_page_numbers,
)
from jurisnexo.ingestion.scanned_page_materialization import LogicalPageRegion, PhysicalPageLayout

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _page(number: int, text: str) -> PhysicalPageLayout:
    return PhysicalPageLayout(
        physical_page_number=number,
        width=100.0,
        height=100.0,
        regions=(
            LogicalPageRegion(
                physical_page_number=number,
                side="left",
                x_min=0.0,
                x_max=50.0,
                text=text,
                printed_page_candidates=(),
            ),
            LogicalPageRegion(
                physical_page_number=number,
                side="right",
                x_min=50.0,
                x_max=100.0,
                text="",
                printed_page_candidates=(),
            ),
        ),
    )


def test_parse_pdfimages_page_numbers_deduplicates_multiple_images_per_page() -> None:
    output = """
page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image    100   100  rgb     3   8  jpeg   no        10  0    72    72  10K  20%
   1     1 image     20    20  rgb     3   8  image  no        11  0    72    72   1K  10%
   3     2 image    100   100  gray    1   8  jpeg   no        12  0    72    72   8K  15%
"""

    assert parse_pdfimages_page_numbers(output) == frozenset({1, 3})


def test_profile_detects_scanned_image_with_text_layer() -> None:
    pages = (_page(1, "a" * 30), _page(2, "b" * 30))

    profile = build_artifact_inspection_profile(
        physical_pages=pages,
        image_page_numbers={1, 2},
    )

    assert profile.suspected_rendering_mode == "scanned_image_with_text_layer"
    assert profile.pages_with_extractable_text == 2
    assert profile.pages_with_images == 2
    assert profile.pages_with_text_and_images == 2


def test_profile_detects_mixed_document() -> None:
    pages = (_page(1, "a" * 30), _page(2, ""), _page(3, "c" * 30))

    profile = build_artifact_inspection_profile(
        physical_pages=pages,
        image_page_numbers={2, 3},
    )

    assert profile.suspected_rendering_mode == "mixed"
    assert profile.pages_with_extractable_text == 2
    assert profile.pages_with_images == 2
    assert profile.pages_with_text_and_images == 1
