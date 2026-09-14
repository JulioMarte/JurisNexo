from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jurisnexo.ingestion.logical_document_view import LogicalDocumentView

PageMapSide = Literal["left", "right"]
PageMapResolutionMethod = Literal["observed_sequence_consistent"]


class PageMapEntry(BaseModel):
    """One stable identity mapping between agent view, source scans, and printed pagination."""

    model_config = ConfigDict(extra="forbid")

    view_page: int = Field(ge=1)
    side: PageMapSide
    physical_pages: tuple[int, ...] = Field(min_length=1)
    representative_physical_page: int = Field(ge=1)
    printed_page_candidates: tuple[int, ...] = ()
    resolved_printed_page: int | None = Field(default=None, ge=1)
    resolution_method: PageMapResolutionMethod | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> PageMapEntry:
        if self.representative_physical_page not in self.physical_pages:
            raise ValueError("representative physical page must belong to physical_pages")
        if len(set(self.physical_pages)) != len(self.physical_pages):
            raise ValueError("physical_pages must not contain duplicates")
        if tuple(sorted(self.physical_pages)) != self.physical_pages:
            raise ValueError("physical_pages must be ordered")
        if self.resolved_printed_page is None and self.resolution_method is not None:
            raise ValueError("resolution_method requires a resolved printed page")
        if self.resolved_printed_page is not None:
            if self.resolution_method is None:
                raise ValueError("resolved printed page requires a resolution_method")
            if self.resolved_printed_page not in self.printed_page_candidates:
                raise ValueError("resolved printed page must be visibly observed as a candidate")
        return self


class PageMap(BaseModel):
    """Auditable pagination map derived from immutable source-page evidence."""

    model_config = ConfigDict(extra="forbid")

    entries: tuple[PageMapEntry, ...] = Field(min_length=1)
    scan_group_count: int = Field(ge=1)
    dominant_printed_page_offset: int | None = None
    dominant_offset_support: int = Field(ge=0)
    pages_with_printed_candidates: int = Field(ge=0)
    resolved_printed_page_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_map(self) -> PageMap:
        expected_view_pages = tuple(range(1, len(self.entries) + 1))
        observed_view_pages = tuple(entry.view_page for entry in self.entries)
        if observed_view_pages != expected_view_pages:
            raise ValueError("PageMap entries must be contiguous and ordered by view_page")
        observed_resolved = sum(
            entry.resolved_printed_page is not None for entry in self.entries
        )
        if observed_resolved != self.resolved_printed_page_count:
            raise ValueError("resolved_printed_page_count does not match entries")
        observed_candidates = sum(bool(entry.printed_page_candidates) for entry in self.entries)
        if observed_candidates != self.pages_with_printed_candidates:
            raise ValueError("pages_with_printed_candidates does not match entries")
        return self

    def get_view_page(self, view_page: int) -> PageMapEntry:
        if view_page < 1 or view_page > len(self.entries):
            raise KeyError(f"view page {view_page} is not present in PageMap")
        return self.entries[view_page - 1]

    def get_printed_page(self, printed_page: int) -> PageMapEntry:
        matches = [
            entry for entry in self.entries if entry.resolved_printed_page == printed_page
        ]
        if not matches:
            raise KeyError(f"printed page {printed_page} is not resolved in PageMap")
        if len(matches) > 1:
            raise ValueError(f"printed page {printed_page} resolves to multiple view pages")
        return matches[0]


def build_page_map(view: LogicalDocumentView) -> PageMap:
    """Materialize typed page identity without inventing unobserved printed pagination."""

    return PageMap(
        entries=tuple(
            PageMapEntry(
                view_page=page.view_page_number,
                side=page.side,
                physical_pages=page.source_physical_pages,
                representative_physical_page=page.representative_physical_page,
                printed_page_candidates=page.printed_page_candidates,
                resolved_printed_page=page.resolved_printed_page,
                resolution_method=page.printed_page_resolution_method,
            )
            for page in view.pages
        ),
        scan_group_count=view.scan_group_count,
        dominant_printed_page_offset=view.dominant_printed_page_offset,
        dominant_offset_support=view.dominant_offset_support,
        pages_with_printed_candidates=view.pages_with_printed_candidates,
        resolved_printed_page_count=view.resolved_printed_page_count,
    )