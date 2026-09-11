from __future__ import annotations

import pytest

from jurisnexo.ingestion.scanned_page_materialization import (
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
    sanitize_bbox_layout_xml,
)

pytestmark = pytest.mark.unit


def _bbox_page(*, left_page: str, right_page: str, left_body: str, right_body: str) -> str:
    return f"""\
<page width="800" height="600">
  <flow><block><line>
    <word xMin="35" yMin="30" xMax="55" yMax="40">{left_page}</word>
    <word xMin="85" yMin="100" xMax="160" yMax="112">{left_body}</word>
  </line></block></flow>
  <flow><block><line>
    <word xMin="745" yMin="30" xMax="770" yMax="40">{right_page}</word>
    <word xMin="500" yMin="100" xMax="620" yMax="112">{right_body}</word>
  </line></block></flow>
</page>
"""


def _document(*pages: str) -> str:
    rendered = "".join(pages)
    return f"""\
<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>{rendered}</doc></body></html>
"""


def test_parse_bbox_layout_splits_spread_and_detects_printed_pages() -> None:
    layouts = parse_bbox_layout(
        _document(
            _bbox_page(
                left_page="184",
                right_page="185",
                left_body="Considerando",
                right_body="Sentencia",
            )
        )
    )

    assert len(layouts) == 1
    page = layouts[0]
    assert page.physical_page_number == 1
    assert page.printed_page_candidates == (184, 185)
    assert page.regions[0].side == "left"
    assert page.regions[0].printed_page_candidates == (184,)
    assert "Considerando" in page.regions[0].text
    assert page.regions[1].side == "right"
    assert page.regions[1].printed_page_candidates == (185,)
    assert "Sentencia" in page.regions[1].text


def test_printed_page_detection_ignores_year_in_outer_header() -> None:
    xml = """\
<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>
<page width="800" height="600"><flow><block><line>
<word xMin="700" yMin="30" xMax="735" yMax="40">1980</word>
<word xMin="750" yMin="30" xMax="770" yMax="40">183</word>
</line></block></flow></page>
</doc></body></html>
"""
    page = parse_bbox_layout(xml)[0]
    assert page.printed_page_candidates == (183,)


def test_bbox_parser_replaces_only_xml_forbidden_ocr_controls() -> None:
    xml = _document(
        _bbox_page(
            left_page="184",
            right_page="185",
            left_body="c\x12isacion",
            right_body="Sentencia",
        )
    )

    sanitized, replacement_count = sanitize_bbox_layout_xml(xml)
    layouts = parse_bbox_layout(xml)

    assert replacement_count == 1
    assert "\x12" not in sanitized
    assert "c�isacion" in layouts[0].regions[0].text


def test_duplicate_detection_flags_similar_adjacent_scans_without_collapsing() -> None:
    layouts = parse_bbox_layout(
        _document(
            _bbox_page(
                left_page="184",
                right_page="185",
                left_body="Considerando recurso casacion recurrente sentencia",
                right_body="Fallo recurso casacion recurrente sentencia",
            ),
            _bbox_page(
                left_page="184",
                right_page="185",
                left_body="Considerando recurso casacion recurrente sentencia",
                right_body="Fallo recurso casacion recurrente sentencia",
            ),
            _bbox_page(
                left_page="186",
                right_page="187",
                left_body="Texto completamente distinto siguiente pagina",
                right_body="Otros hechos y fundamentos",
            ),
        )
    )

    duplicates = detect_adjacent_duplicate_scans(layouts, minimum_token_jaccard=0.70)

    assert len(layouts) == 3
    assert len(duplicates) == 1
    duplicate = duplicates[0]
    assert duplicate.first_physical_page == 1
    assert duplicate.second_physical_page == 2
    assert duplicate.shared_printed_page_candidates == (184, 185)
    assert duplicate.token_jaccard == pytest.approx(1.0)
