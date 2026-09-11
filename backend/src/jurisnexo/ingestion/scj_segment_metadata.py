from __future__ import annotations

from jurisnexo.ingestion.scj_layouts import SCJLayoutFamily, detect_scj_page_layout
from jurisnexo.ingestion.scj_metadata import MetadataObservation, parse_scj_page_metadata
from jurisnexo.ingestion.scj_segmentation import CaseSegment

_OLD_FAMILIES = {
    SCJLayoutFamily.PRINCIPALES_2023_2024_SENTENCE,
    SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION,
}
_MODERN_FAMILIES = {
    SCJLayoutFamily.PRINCIPALES_2025_PRIMERA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_SEGUNDA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_TERCERA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_PLENO_RESOLUTION,
}


def parse_scj_segment_metadata(
    pages: list[str], segment: CaseSegment
) -> list[MetadataObservation]:
    """Extract metadata from the page that establishes segment identity.

    For 2023/2024 publications, a formal case-start heading establishes the
    segment and later body pages may contain cited decisions and procedural
    dates. Only the start page is metadata-bearing.

    The observed 2025 generation repeats structured headers on continuation
    pages. Those repeated headers are valuable for segmentation, but parsing
    every continuation page as metadata reintroduces cited SCJ numbers and
    historical dates from body text. Therefore the start page is the default
    metadata authority for modern segments as well. A future layout that needs
    continuation-page recovery must add a field-specific, tested fallback rather
    than scanning every body page by default.
    """
    if segment.start_page <= 0 or segment.end_page < segment.start_page:
        raise ValueError("invalid segment page range")
    if segment.end_page > len(pages):
        raise ValueError("segment page range exceeds document")

    if segment.family in _OLD_FAMILIES:
        return parse_scj_page_metadata(
            pages[segment.start_page - 1], page_number=segment.start_page
        )

    if segment.family in _MODERN_FAMILIES:
        text = pages[segment.start_page - 1]
        detection = detect_scj_page_layout(text, page_number=segment.start_page)
        if (
            detection.family is segment.family
            and detection.signature_key == segment.signature_key
        ):
            return parse_scj_page_metadata(text, page_number=segment.start_page)
        return []

    return []
