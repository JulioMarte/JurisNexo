from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Literal

from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.scanned_page_materialization import (
    AdjacentDuplicateScan,
    LogicalPageRegion,
    PageSide,
    PhysicalPageLayout,
)

PrintedPageResolutionMethod = Literal["observed_sequence_consistent"]


@dataclass(frozen=True, slots=True)
class LogicalDocumentPage:
    """Agent-facing logical page with immutable physical-page provenance."""

    view_page_number: int
    side: PageSide
    source_physical_pages: tuple[int, ...]
    representative_physical_page: int
    text: str
    printed_page_candidates: tuple[int, ...]
    resolved_printed_page: int | None = None
    printed_page_resolution_method: PrintedPageResolutionMethod | None = None


@dataclass(frozen=True, slots=True)
class LogicalDocumentView:
    pages: tuple[LogicalDocumentPage, ...]
    scan_group_count: int
    dominant_printed_page_offset: int | None
    dominant_offset_support: int
    pages_with_printed_candidates: int
    resolved_printed_page_count: int


class LogicalDocumentViewError(ValueError):
    """Raised when physical-page provenance cannot form a safe logical view."""


def materialize_logical_document_view(
    *,
    physical_pages: tuple[PhysicalPageLayout, ...],
    duplicate_scans: tuple[AdjacentDuplicateScan, ...],
    minimum_region_characters: int = 80,
    minimum_sequence_support: int = 8,
    minimum_sequence_share: float = 0.60,
) -> LogicalDocumentView:
    """Build a deduplicated read view without deleting source-page provenance.

    Duplicate physical scans become equivalence groups. Each non-trivial left or
    right region becomes one view page backed by every physical page in that
    group. Printed page numbers are resolved only when they are visibly observed
    and agree with a dominant sequence offset; missing numbers are never filled
    merely because continuity would make them plausible.
    """

    if not physical_pages:
        raise LogicalDocumentViewError("physical_pages must not be empty")
    if minimum_region_characters < 1:
        raise LogicalDocumentViewError("minimum_region_characters must be positive")
    if minimum_sequence_support < 2:
        raise LogicalDocumentViewError("minimum_sequence_support must be at least 2")
    if not 0.0 < minimum_sequence_share <= 1.0:
        raise LogicalDocumentViewError("minimum_sequence_share must be within (0, 1]")

    page_by_number = _page_index(physical_pages)
    scan_groups = _build_scan_groups(
        physical_page_numbers=tuple(page_by_number),
        duplicate_scans=duplicate_scans,
    )

    pages: list[LogicalDocumentPage] = []
    for scan_group in scan_groups:
        group_pages = tuple(page_by_number[number] for number in scan_group)
        for side_index, side in enumerate(("left", "right")):
            regions = tuple(page.regions[side_index] for page in group_pages)
            representative = _representative_region(regions)
            if _visible_character_count(representative.text) < minimum_region_characters:
                continue
            candidates = tuple(
                sorted(
                    {
                        candidate
                        for region in regions
                        for candidate in region.printed_page_candidates
                    }
                )
            )
            pages.append(
                LogicalDocumentPage(
                    view_page_number=len(pages) + 1,
                    side=side,
                    source_physical_pages=scan_group,
                    representative_physical_page=representative.physical_page_number,
                    text=representative.text,
                    printed_page_candidates=candidates,
                )
            )

    if not pages:
        raise LogicalDocumentViewError("no logical pages survived region filtering")

    offset, support, candidate_page_count = _dominant_printed_page_offset(tuple(pages))
    if (
        offset is None
        or support < minimum_sequence_support
        or support / max(candidate_page_count, 1) < minimum_sequence_share
    ):
        return LogicalDocumentView(
            pages=tuple(pages),
            scan_group_count=len(scan_groups),
            dominant_printed_page_offset=None,
            dominant_offset_support=0,
            pages_with_printed_candidates=candidate_page_count,
            resolved_printed_page_count=0,
        )

    resolved: list[LogicalDocumentPage] = []
    resolved_count = 0
    for page in pages:
        expected = page.view_page_number + offset
        if expected in page.printed_page_candidates:
            resolved.append(
                replace(
                    page,
                    resolved_printed_page=expected,
                    printed_page_resolution_method="observed_sequence_consistent",
                )
            )
            resolved_count += 1
        else:
            resolved.append(page)

    return LogicalDocumentView(
        pages=tuple(resolved),
        scan_group_count=len(scan_groups),
        dominant_printed_page_offset=offset,
        dominant_offset_support=support,
        pages_with_printed_candidates=candidate_page_count,
        resolved_printed_page_count=resolved_count,
    )


def build_document_environment_from_logical_view(
    view: LogicalDocumentView,
    *,
    max_page_chars: int = 12_000,
) -> DocumentEnvironment:
    """Expose the derived logical view to an agent with physical provenance."""

    return DocumentEnvironment(
        pages=tuple(page.text for page in view.pages),
        max_page_chars=max_page_chars,
        printed_page_numbers=tuple(page.resolved_printed_page for page in view.pages),
        source_references=tuple(_source_reference(page) for page in view.pages),
    )


def _source_reference(page: LogicalDocumentPage) -> str:
    physical_pages = ",".join(str(number) for number in page.source_physical_pages)
    return (
        f"physical_pages={physical_pages}; side={page.side}; "
        f"representative_physical_page={page.representative_physical_page}"
    )


def _page_index(
    physical_pages: tuple[PhysicalPageLayout, ...],
) -> dict[int, PhysicalPageLayout]:
    index: dict[int, PhysicalPageLayout] = {}
    for expected, page in enumerate(physical_pages, start=1):
        if page.physical_page_number != expected:
            raise LogicalDocumentViewError(
                "physical page numbering must be contiguous and ordered from 1"
            )
        index[page.physical_page_number] = page
    return index


def _build_scan_groups(
    *,
    physical_page_numbers: tuple[int, ...],
    duplicate_scans: tuple[AdjacentDuplicateScan, ...],
) -> tuple[tuple[int, ...], ...]:
    duplicate_by_first: dict[int, int] = {}
    duplicate_seconds: set[int] = set()
    known_pages = set(physical_page_numbers)

    for duplicate in duplicate_scans:
        first = duplicate.first_physical_page
        second = duplicate.second_physical_page
        if second != first + 1:
            raise LogicalDocumentViewError("duplicate scan observations must be adjacent")
        if first not in known_pages or second not in known_pages:
            raise LogicalDocumentViewError("duplicate scan references an unknown physical page")
        if first in duplicate_by_first or first in duplicate_seconds or second in duplicate_seconds:
            raise LogicalDocumentViewError("overlapping duplicate scan observations are ambiguous")
        duplicate_by_first[first] = second
        duplicate_seconds.add(second)

    groups: list[tuple[int, ...]] = []
    index = 0
    while index < len(physical_page_numbers):
        current = physical_page_numbers[index]
        duplicate_second = duplicate_by_first.get(current)
        if duplicate_second is not None:
            groups.append((current, duplicate_second))
            index += 2
            continue
        if current in duplicate_seconds:
            raise LogicalDocumentViewError("duplicate second page was not consumed with its first")
        groups.append((current,))
        index += 1
    return tuple(groups)


def _representative_region(regions: tuple[LogicalPageRegion, ...]) -> LogicalPageRegion:
    return max(
        regions,
        key=lambda region: (
            _visible_character_count(region.text),
            len(region.text),
            -region.physical_page_number,
        ),
    )


def _dominant_printed_page_offset(
    pages: tuple[LogicalDocumentPage, ...],
) -> tuple[int | None, int, int]:
    offsets: Counter[int] = Counter()
    pages_with_candidates = 0
    for page in pages:
        if not page.printed_page_candidates:
            continue
        pages_with_candidates += 1
        for candidate in page.printed_page_candidates:
            offsets[candidate - page.view_page_number] += 1

    if not offsets:
        return None, 0, pages_with_candidates

    top = offsets.most_common(2)
    offset, support = top[0]
    if len(top) > 1 and top[1][1] == support:
        return None, 0, pages_with_candidates
    return offset, support, pages_with_candidates


def _visible_character_count(value: str) -> int:
    return sum(1 for character in value if not character.isspace())
