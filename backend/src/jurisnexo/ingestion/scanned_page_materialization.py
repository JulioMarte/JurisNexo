from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET

PageSide = Literal["left", "right"]
_XHTML_NS = "http://www.w3.org/1999/xhtml"
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}")
_PRINTED_PAGE_PATTERN = re.compile(r"\d{1,4}")


@dataclass(frozen=True, slots=True)
class LogicalPageRegion:
    physical_page_number: int
    side: PageSide
    x_min: float
    x_max: float
    text: str
    printed_page_candidates: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PhysicalPageLayout:
    physical_page_number: int
    width: float
    height: float
    regions: tuple[LogicalPageRegion, ...]

    @property
    def text(self) -> str:
        return "\n".join(region.text for region in self.regions if region.text)

    @property
    def printed_page_candidates(self) -> tuple[int, ...]:
        values = {
            candidate
            for region in self.regions
            for candidate in region.printed_page_candidates
        }
        return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class AdjacentDuplicateScan:
    first_physical_page: int
    second_physical_page: int
    token_jaccard: float
    shared_printed_page_candidates: tuple[int, ...]


def parse_bbox_layout(xml_text: str) -> tuple[PhysicalPageLayout, ...]:
    """Convert Poppler bbox-layout XHTML into left/right logical page regions.

    A physical PDF page remains the provenance unit. Logical regions are derived
    views and must never replace or delete the source physical page.
    """

    root = ET.fromstring(xml_text)
    namespace = {"x": _XHTML_NS}
    pages: list[PhysicalPageLayout] = []

    for page_number, page in enumerate(root.findall(".//x:page", namespace), start=1):
        width = float(page.attrib["width"])
        height = float(page.attrib["height"])
        midpoint = width / 2.0
        left_lines: list[str] = []
        right_lines: list[str] = []
        left_words: list[tuple[str, float, float]] = []
        right_words: list[tuple[str, float, float]] = []

        for line in page.findall(".//x:line", namespace):
            left_parts: list[str] = []
            right_parts: list[str] = []
            for word in line.findall("x:word", namespace):
                text = "".join(word.itertext()).strip()
                if not text:
                    continue
                x_min = float(word.attrib["xMin"])
                x_max = float(word.attrib["xMax"])
                y_min = float(word.attrib["yMin"])
                x_center = (x_min + x_max) / 2.0
                if x_center < midpoint:
                    left_parts.append(text)
                    left_words.append((text, x_center, y_min))
                else:
                    right_parts.append(text)
                    right_words.append((text, x_center, y_min))
            if left_parts:
                left_lines.append(" ".join(left_parts))
            if right_parts:
                right_lines.append(" ".join(right_parts))

        regions = (
            LogicalPageRegion(
                physical_page_number=page_number,
                side="left",
                x_min=0.0,
                x_max=midpoint,
                text="\n".join(left_lines),
                printed_page_candidates=_printed_page_candidates(
                    words=left_words,
                    side="left",
                    page_width=width,
                    page_height=height,
                ),
            ),
            LogicalPageRegion(
                physical_page_number=page_number,
                side="right",
                x_min=midpoint,
                x_max=width,
                text="\n".join(right_lines),
                printed_page_candidates=_printed_page_candidates(
                    words=right_words,
                    side="right",
                    page_width=width,
                    page_height=height,
                ),
            ),
        )
        pages.append(
            PhysicalPageLayout(
                physical_page_number=page_number,
                width=width,
                height=height,
                regions=regions,
            )
        )

    return tuple(pages)


def detect_adjacent_duplicate_scans(
    pages: tuple[PhysicalPageLayout, ...],
    *,
    minimum_token_jaccard: float = 0.70,
) -> tuple[AdjacentDuplicateScan, ...]:
    """Flag likely duplicate adjacent scans without collapsing provenance."""

    if not 0.0 <= minimum_token_jaccard <= 1.0:
        raise ValueError("minimum_token_jaccard must be between 0 and 1")

    duplicates: list[AdjacentDuplicateScan] = []
    for first, second in zip(pages, pages[1:], strict=False):
        first_tokens = _tokens(first.text)
        second_tokens = _tokens(second.text)
        if not first_tokens or not second_tokens:
            continue
        similarity = len(first_tokens & second_tokens) / len(first_tokens | second_tokens)
        if similarity < minimum_token_jaccard:
            continue

        first_candidates = set(first.printed_page_candidates)
        second_candidates = set(second.printed_page_candidates)
        shared = tuple(sorted(first_candidates & second_candidates))
        if first_candidates and second_candidates and not shared:
            continue

        duplicates.append(
            AdjacentDuplicateScan(
                first_physical_page=first.physical_page_number,
                second_physical_page=second.physical_page_number,
                token_jaccard=similarity,
                shared_printed_page_candidates=shared,
            )
        )

    return tuple(duplicates)


def _printed_page_candidates(
    *,
    words: list[tuple[str, float, float]],
    side: PageSide,
    page_width: float,
    page_height: float,
) -> tuple[int, ...]:
    candidates: set[int] = set()
    for text, x_center, y_min in words:
        if y_min > page_height * 0.18 or _PRINTED_PAGE_PATTERN.fullmatch(text) is None:
            continue
        value = int(text)
        if value == 0 or 1900 <= value <= 2100:
            continue
        if side == "left" and x_center > page_width * 0.25:
            continue
        if side == "right" and x_center < page_width * 0.75:
            continue
        candidates.add(value)
    return tuple(sorted(candidates))


def _tokens(value: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(value)}
