from __future__ import annotations

from jurisnexo.acquisition.completeness import SourceInventorySnapshot
from jurisnexo.acquisition.official_corpus import (
    SCJ_MEGAQUERY_URL,
    HttpFetcher,
    crawl_tc_candidates,
    discover_scj_pdf_candidates_from_html,
)


def build_tc_complete_inventory(fetcher: HttpFetcher) -> SourceInventorySnapshot:
    """Enumerate the TC all-sentences surface, which is explicitly requested as one full page."""

    candidates = crawl_tc_candidates(fetcher)
    return SourceInventorySnapshot(
        source="constitutional_court",
        candidates=candidates,
        enumeration_complete=True,
        enumeration_basis=(
            "official Tribunal Constitucional all-sentences listing requested with size=999999; "
            "every discovered sentence detail page is resolved to its official PDF"
        ),
    )


def build_scj_landing_inventory(fetcher: HttpFetcher) -> SourceInventorySnapshot:
    """Inspect the SCJ landing page without falsely claiming it enumerates all judgments."""

    html = fetcher.get_bytes(SCJ_MEGAQUERY_URL).decode("utf-8", errors="replace")
    candidates = discover_scj_pdf_candidates_from_html(
        html=html,
        page_url=SCJ_MEGAQUERY_URL,
    )
    return SourceInventorySnapshot(
        source="supreme_court",
        candidates=candidates,
        enumeration_complete=False,
        enumeration_basis=(
            "SCJ megaconsulta landing HTML is a search form, not a complete result enumeration; "
            "a verified year/month query contract is still required before 100% certification"
        ),
    )
