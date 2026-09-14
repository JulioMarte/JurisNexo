from __future__ import annotations

import re
from collections.abc import Collection

from jurisnexo.ingestion.scanned_page_materialization import PhysicalPageLayout
from jurisnexo.ingestion.structure_trace import ArtifactInspectionProfile

_PDFIMAGES_ROW = re.compile(r"^\s*(\d+)\s+\d+\s+")


def parse_pdfimages_page_numbers(output: str) -> frozenset[int]:
    """Extract PDF page numbers that contain at least one image from `pdfimages -list`."""

    pages: set[int] = set()
    for line in output.splitlines():
        match = _PDFIMAGES_ROW.match(line)
        if match is not None:
            pages.add(int(match.group(1)))
    return frozenset(pages)


def build_artifact_inspection_profile(
    *,
    physical_pages: tuple[PhysicalPageLayout, ...],
    image_page_numbers: Collection[int] | None,
    minimum_extractable_characters: int = 20,
    profile_method: str = "poppler_bbox_plus_pdfimages",
) -> ArtifactInspectionProfile:
    """Classify rendering composition from deterministic extraction signals.

    This does not decide document structure. It only exposes measurable facts that the
    Structure Agent can use when choosing which inspection tools to trust.
    """

    if not physical_pages:
        raise ValueError("physical_pages must not be empty")
    if minimum_extractable_characters < 1:
        raise ValueError("minimum_extractable_characters must be positive")

    physical_page_count = len(physical_pages)
    text_pages = {
        page.physical_page_number
        for page in physical_pages
        if len(page.text.strip()) >= minimum_extractable_characters
    }

    if image_page_numbers is None:
        return ArtifactInspectionProfile(
            physical_page_count=physical_page_count,
            pages_with_extractable_text=len(text_pages),
            suspected_rendering_mode="unknown",
            profile_method=profile_method,
            notes=["image composition was not measured"],
        )

    image_pages = {page for page in image_page_numbers if 1 <= page <= physical_page_count}
    text_and_image_pages = text_pages & image_pages

    if image_pages and not text_pages:
        mode = "scanned_image"
    elif not image_pages and text_pages:
        mode = "born_digital_text"
    elif (
        len(image_pages) == physical_page_count
        and len(text_pages) == physical_page_count
        and text_and_image_pages == image_pages
    ):
        mode = "scanned_image_with_text_layer"
    elif image_pages and text_pages:
        mode = "mixed"
    else:
        mode = "unknown"

    notes: list[str] = []
    if image_pages and text_pages:
        notes.append(
            "image and extractable-text signals can coexist because scanned PDFs may "
            "carry hidden OCR"
        )
    if len(text_pages) != physical_page_count:
        missing_text_count = physical_page_count - len(text_pages)
        notes.append(
            f"{missing_text_count} physical page(s) have little or no extractable text"
        )

    return ArtifactInspectionProfile(
        physical_page_count=physical_page_count,
        pages_with_extractable_text=len(text_pages),
        pages_with_images=len(image_pages),
        pages_with_text_and_images=len(text_and_image_pages),
        suspected_rendering_mode=mode,
        profile_method=profile_method,
        notes=notes,
    )
