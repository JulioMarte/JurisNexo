from __future__ import annotations

import pytest

from jurisnexo.acquisition.tc_public import discover_tc_pdf_url


def test_tc_detail_discovery_resolves_official_pdf_without_engine_knowledge() -> None:
    html = """
    <html>
      <body>
        <iframe src="/media/sentencias/tc-0001-26-tc-04-2025-0258.pdf"></iframe>
        <a href="/media/sentencias/tc-0001-26-tc-04-2025-0258.pdf">Descargar</a>
      </body>
    </html>
    """
    url = discover_tc_pdf_url(
        detail_html=html,
        detail_url=(
            "https://tribunalconstitucional.gob.do/"
            "consultas/secretaria/sentencias/tc000126/"
        ),
        expected_filename="tc-0001-26-tc-04-2025-0258.pdf",
    )
    assert url == (
        "https://tribunalconstitucional.gob.do/"
        "media/sentencias/tc-0001-26-tc-04-2025-0258.pdf"
    )


def test_tc_detail_discovery_fails_closed_on_ambiguous_pdf_links() -> None:
    html = """
    <a href="/one.pdf">one</a>
    <a href="/two.pdf">two</a>
    """
    with pytest.raises(ValueError, match="expected one"):
        discover_tc_pdf_url(
            detail_html=html,
            detail_url="https://tribunalconstitucional.gob.do/detail/",
        )


def test_tc_discovery_collapses_pdfjs_viewer_and_direct_download() -> None:
    direct = (
        "https://tribunalsitestorage.blob.core.windows.net/"
        "media/66195/tc-0001-26-tc-04-2025-0258.pdf"
    )
    viewer = (
        "https://www.tribunalconstitucional.gob.do/js/pdf/web/viewer.html"
        "?file=https%3A%2F%2Ftribunalsitestorage.blob.core.windows.net%2F"
        "media%2F66195%2Ftc-0001-26-tc-04-2025-0258.pdf"
    )
    html = f"""
    <a href="{direct}">Descargar</a>
    <iframe src="{viewer}"></iframe>
    """
    assert discover_tc_pdf_url(
        detail_html=html,
        detail_url=(
            "https://www.tribunalconstitucional.gob.do/"
            "consultas/secretaria/sentencias/tc000126/"
        ),
        expected_filename="tc-0001-26-tc-04-2025-0258.pdf",
    ) == direct
