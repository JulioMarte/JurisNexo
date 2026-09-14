from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurisnexo.ingestion.logical_document_view import (
    LogicalDocumentPage,
    LogicalDocumentView,
)
from jurisnexo.ingestion.page_map import PageMapEntry, build_page_map

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _logical_view() -> LogicalDocumentView:
    return LogicalDocumentView(
        pages=(
            LogicalDocumentPage(
                view_page_number=1,
                side="left",
                source_physical_pages=(5, 6),
                representative_physical_page=5,
                text="page 183",
                printed_page_candidates=(183,),
                resolved_printed_page=183,
                printed_page_resolution_method="observed_sequence_consistent",
            ),
            LogicalDocumentPage(
                view_page_number=2,
                side="right",
                source_physical_pages=(5, 6),
                representative_physical_page=6,
                text="unresolved page",
                printed_page_candidates=(),
            ),
        ),
        scan_group_count=1,
        dominant_printed_page_offset=182,
        dominant_offset_support=1,
        pages_with_printed_candidates=1,
        resolved_printed_page_count=1,
    )


def test_page_map_preserves_view_printed_and_physical_identity() -> None:
    page_map = build_page_map(_logical_view())

    printed = page_map.get_printed_page(183)
    assert printed.view_page == 1
    assert printed.physical_pages == (5, 6)
    assert printed.representative_physical_page == 5
    assert printed.side == "left"
    assert printed.resolution_method == "observed_sequence_consistent"

    unresolved = page_map.get_view_page(2)
    assert unresolved.resolved_printed_page is None
    assert unresolved.resolution_method is None


def test_page_map_does_not_resolve_unobserved_printed_pages() -> None:
    page_map = build_page_map(_logical_view())

    with pytest.raises(KeyError, match="184"):
        page_map.get_printed_page(184)


def test_page_map_rejects_resolved_page_not_present_in_observed_candidates() -> None:
    with pytest.raises(ValidationError, match="visibly observed"):
        PageMapEntry(
            view_page=1,
            side="left",
            physical_pages=(1,),
            representative_physical_page=1,
            printed_page_candidates=(182,),
            resolved_printed_page=183,
            resolution_method="observed_sequence_consistent",
        )


def test_page_map_rejects_representative_outside_source_pages() -> None:
    with pytest.raises(ValidationError, match="must belong"):
        PageMapEntry(
            view_page=1,
            side="right",
            physical_pages=(1, 2),
            representative_physical_page=3,
        )