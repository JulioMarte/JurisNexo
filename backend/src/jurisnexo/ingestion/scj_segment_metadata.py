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
    """Extract case metadata only from pages that prove the segment identity.

    2023/2024 compilations expose a formal case-start heading and then ordinary
    body pages. Parsing body pages as identity metadata creates false candidates
    from cited SCJ decisions and historical procedural dates, so only the start
    page is metadata-bearing for these publication families.

    The observed 2025 generation repeats a structured case header on its pages.
    Metadata is accepted only from pages whose independently detected family and
    signature match the segment. Bridged/unknown pages remain case text but do
    not become metadata evidence.
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
        observations: list[MetadataObservation] = []
        for page_number in range(segment.start_page, segment.end_page + 1):
            text = pages[page_number - 1]
            detection = detect_scj_page_layout(text, page_number=page_number)
            if (
                detection.family is segment.family
                and detection.signature_key == segment.signature_key
            ):
                observations.extend(
                    parse_scj_page_metadata(text, page_number=page_number)
                )
        return observations

    return []
