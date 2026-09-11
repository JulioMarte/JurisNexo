from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jurisnexo.ingestion.scj_layouts import (
    LayoutDetectionStatus,
    PageLayoutDetection,
    SCJLayoutFamily,
    detect_scj_page_layout,
)


class SegmentationStatus(StrEnum):
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class CaseSegment:
    start_page: int
    end_page: int
    family: SCJLayoutFamily
    signature_key: str
    status: SegmentationStatus
    diagnostics: tuple[str, ...] = ()


_OLD_BOUNDARY_FAMILIES = {
    SCJLayoutFamily.PRINCIPALES_2023_2024_SENTENCE,
    SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION,
}
_MODERN_REPEATED_HEADER_FAMILIES = {
    SCJLayoutFamily.PRINCIPALES_2025_PRIMERA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_SEGUNDA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_TERCERA_SALA,
    SCJLayoutFamily.PRINCIPALES_2025_PLENO_RESOLUTION,
}


def _bridge_short_modern_gaps(
    detections: list[PageLayoutDetection], *, max_gap: int
) -> list[PageLayoutDetection]:
    if max_gap <= 0:
        return detections

    result = detections[:]
    index = 0
    while index < len(result):
        if result[index].status is not LayoutDetectionStatus.UNKNOWN:
            index += 1
            continue

        gap_start = index
        while index < len(result) and result[index].status is LayoutDetectionStatus.UNKNOWN:
            index += 1
        gap_end = index
        gap_size = gap_end - gap_start

        if gap_start == 0 or gap_end >= len(result) or gap_size > max_gap:
            continue

        left = result[gap_start - 1]
        right = result[gap_end]
        if (
            left.family in _MODERN_REPEATED_HEADER_FAMILIES
            and left.family == right.family
            and left.signature_key is not None
            and left.signature_key == right.signature_key
        ):
            for position in range(gap_start, gap_end):
                original = result[position]
                result[position] = PageLayoutDetection(
                    page_number=original.page_number,
                    family=left.family,
                    status=LayoutDetectionStatus.RECOGNIZED,
                    signature_key=left.signature_key,
                    primary_decision_number=left.primary_decision_number,
                    header_date=left.header_date,
                    evidence=left.evidence + ("bridged_unknown_page",),
                )

    return result


def _segment_old_publication(
    pages: list[str], detections: list[PageLayoutDetection]
) -> list[CaseSegment]:
    starts = [
        detection
        for detection in detections
        if detection.family in _OLD_BOUNDARY_FAMILIES
        and detection.signature_key is not None
    ]
    segments: list[CaseSegment] = []
    for index, detection in enumerate(starts):
        end_page = (
            starts[index + 1].page_number - 1
            if index + 1 < len(starts)
            else len(pages)
        )
        segments.append(
            CaseSegment(
                start_page=detection.page_number,
                end_page=end_page,
                family=detection.family,
                signature_key=detection.signature_key or "",
                status=SegmentationStatus.CANDIDATE,
            )
        )
    return segments


def _segment_modern_repeated_headers(
    detections: list[PageLayoutDetection], *, max_gap: int
) -> tuple[list[CaseSegment], list[PageLayoutDetection]]:
    effective = _bridge_short_modern_gaps(detections, max_gap=max_gap)
    segments: list[CaseSegment] = []
    active_start: int | None = None
    active_end: int | None = None
    active_family: SCJLayoutFamily | None = None
    active_key: str | None = None

    for detection in effective:
        if (
            detection.family not in _MODERN_REPEATED_HEADER_FAMILIES
            or detection.signature_key is None
        ):
            continue

        identity = (detection.family, detection.signature_key)
        if active_start is None:
            active_start = detection.page_number
            active_end = detection.page_number
            active_family, active_key = identity
            continue

        if (
            identity == (active_family, active_key)
            and detection.page_number == (active_end or 0) + 1
        ):
            active_end = detection.page_number
            continue

        assert active_family is not None
        assert active_key is not None
        assert active_end is not None
        segments.append(
            CaseSegment(
                start_page=active_start,
                end_page=active_end,
                family=active_family,
                signature_key=active_key,
                status=SegmentationStatus.CANDIDATE,
            )
        )
        active_start = detection.page_number
        active_end = detection.page_number
        active_family, active_key = identity

    if active_start is not None:
        assert active_family is not None
        assert active_key is not None
        assert active_end is not None
        segments.append(
            CaseSegment(
                start_page=active_start,
                end_page=active_end,
                family=active_family,
                signature_key=active_key,
                status=SegmentationStatus.CANDIDATE,
            )
        )
    return segments, effective


def segment_scj_pages(
    pages: list[str], *, bridge_unknown_pages: int = 2
) -> tuple[list[CaseSegment], list[PageLayoutDetection]]:
    """Segment one SCJ compilation using the detected publication grammar."""
    detections = [
        detect_scj_page_layout(page, page_number=index + 1)
        for index, page in enumerate(pages)
    ]

    old_boundaries = sum(
        detection.family in _OLD_BOUNDARY_FAMILIES for detection in detections
    )
    modern_headers = sum(
        detection.family in _MODERN_REPEATED_HEADER_FAMILIES
        for detection in detections
    )

    if old_boundaries > 0 and old_boundaries >= modern_headers:
        return _segment_old_publication(pages, detections), detections

    return _segment_modern_repeated_headers(
        detections, max_gap=bridge_unknown_pages
    )
