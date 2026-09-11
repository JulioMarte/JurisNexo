from __future__ import annotations

import pytest

from jurisnexo.ingestion.logical_document_view import (
    build_document_environment_from_logical_view,
    materialize_logical_document_view,
)
from jurisnexo.ingestion.scanned_page_materialization import (
    AdjacentDuplicateScan,
    LogicalPageRegion,
    PageSide,
    PhysicalPageLayout,
    detect_adjacent_duplicate_scans,
)

pytestmark = pytest.mark.unit


def _region(
    page: int,
    side: PageSide,
    text: str,
    candidates: tuple[int, ...] = (),
) -> LogicalPageRegion:
    return LogicalPageRegion(
        physical_page_number=page,
        side=side,
        x_min=0.0 if side == "left" else 400.0,
        x_max=400.0 if side == "left" else 800.0,
        text=text,
        printed_page_candidates=candidates,
    )


def _page(
    number: int,
    *,
    left_text: str,
    right_text: str,
    left_candidates: tuple[int, ...] = (),
    right_candidates: tuple[int, ...] = (),
) -> PhysicalPageLayout:
    return PhysicalPageLayout(
        physical_page_number=number,
        width=800.0,
        height=600.0,
        regions=(
            _region(number, "left", left_text, left_candidates),
            _region(number, "right", right_text, right_candidates),
        ),
    )


def _sample_view():
    pages = (
        _page(
            1,
            left_text="",
            right_text="portada boletin judicial numero ochocientos treinta y uno",
            right_candidates=(831,),
        ),
        _page(
            2,
            left_text="sumario de recursos de casacion",
            right_text="sentencia primera contenido legal",
            right_candidates=(183,),
        ),
        _page(
            3,
            left_text="sumario de recursos de casacion",
            right_text="sentencia primera contenido legal corregido",
            right_candidates=(183,),
        ),
        _page(
            4,
            left_text="continuacion sentencia pagina ciento ochenta y cuatro",
            right_text="continuacion sentencia pagina ciento ochenta y cinco",
            left_candidates=(184,),
            right_candidates=(185,),
        ),
        _page(
            5,
            left_text="continuacion sentencia pagina ciento ochenta y cuatro",
            right_text="continuacion sentencia pagina ciento ochenta y cinco",
            left_candidates=(184,),
            right_candidates=(185,),
        ),
        _page(
            6,
            left_text="labor de la suprema corte sin numero impreso recuperable",
            right_text="",
        ),
    )
    duplicates = (
        AdjacentDuplicateScan(2, 3, 0.90, (183,)),
        AdjacentDuplicateScan(4, 5, 0.95, (184, 185)),
    )
    return materialize_logical_document_view(
        physical_pages=pages,
        duplicate_scans=duplicates,
        minimum_region_characters=1,
        minimum_sequence_support=3,
        minimum_sequence_share=0.70,
    )


def test_duplicate_detection_accepts_borderline_match_only_with_exact_page_evidence() -> None:
    same_candidates = (
        _page(
            1,
            left_text="uno dos tres cuatro cinco",
            right_text="",
            left_candidates=(234, 235),
        ),
        _page(
            2,
            left_text="uno dos tres cuatro seis",
            right_text="",
            left_candidates=(234, 235),
        ),
    )
    different_candidates = (
        same_candidates[0],
        _page(
            2,
            left_text="uno dos tres cuatro seis",
            right_text="",
            left_candidates=(236, 237),
        ),
    )

    corroborated = detect_adjacent_duplicate_scans(same_candidates)
    rejected = detect_adjacent_duplicate_scans(different_candidates)

    assert len(corroborated) == 1
    assert corroborated[0].token_jaccard == pytest.approx(2 / 3)
    assert corroborated[0].shared_printed_page_candidates == (234, 235)
    assert rejected == ()


def test_logical_view_groups_rescans_and_only_resolves_observed_sequence_pages() -> None:
    view = _sample_view()

    assert view.scan_group_count == 4
    assert len(view.pages) == 6
    assert view.dominant_printed_page_offset == 180
    assert view.dominant_offset_support == 3
    assert view.resolved_printed_page_count == 3

    first_case_page = view.pages[2]
    assert first_case_page.source_physical_pages == (2, 3)
    assert first_case_page.resolved_printed_page == 183
    assert first_case_page.printed_page_resolution_method == "observed_sequence_consistent"

    assert view.pages[3].resolved_printed_page == 184
    assert view.pages[4].resolved_printed_page == 185
    assert view.pages[5].resolved_printed_page is None


def test_logical_view_builds_agent_environment_with_source_provenance() -> None:
    environment = build_document_environment_from_logical_view(_sample_view())

    page = environment.get_printed_page(183)

    assert page.page_number == 3
    assert page.printed_page_number == 183
    assert page.source_reference == (
        "physical_pages=2,3; side=right; representative_physical_page=3"
    )
    assert "sentencia primera" in page.text
