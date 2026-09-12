from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from jurisnexo.acquisition.official_corpus import (
    SCJ_MEGAQUERY_URL,
    TC_SENTENCES_URL,
    discover_scj_pdf_candidates_from_html,
    discover_tc_detail_pages,
)

SourceSurface = Literal["scj_megaconsulta", "tc_sentences"]
DriftStatus = Literal["healthy", "source_drift"]


@dataclass(frozen=True, slots=True)
class SourceSurfaceObservation:
    surface: SourceSurface
    url: str
    status: DriftStatus
    html_sha256: str
    byte_count: int
    discovered_item_count: int
    missing_markers: tuple[str, ...]
    reason: str | None

    @property
    def requires_browser_recovery(self) -> bool:
        return self.status == "source_drift"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


def _digest_html(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()


def inspect_tc_sentence_surface(html: str) -> SourceSurfaceObservation:
    markers = ("TC/", "sentencias")
    missing = tuple(marker for marker in markers if marker.casefold() not in html.casefold())
    discovered = discover_tc_detail_pages(html=html, listing_url=TC_SENTENCES_URL)
    drift = bool(missing) or not discovered
    reason = None
    if drift:
        reason = "TC listing no longer satisfies the deterministic sentence-link contract"
    return SourceSurfaceObservation(
        surface="tc_sentences",
        url=TC_SENTENCES_URL,
        status="source_drift" if drift else "healthy",
        html_sha256=_digest_html(html),
        byte_count=len(html.encode("utf-8", errors="replace")),
        discovered_item_count=len(discovered),
        missing_markers=missing,
        reason=reason,
    )


def inspect_scj_megaconsulta_surface(html: str) -> SourceSurfaceObservation:
    markers = ("consulta", "suprema")
    missing = tuple(marker for marker in markers if marker.casefold() not in html.casefold())
    discovered = discover_scj_pdf_candidates_from_html(html=html, page_url=SCJ_MEGAQUERY_URL)
    # The SCJ landing page may legitimately expose zero PDFs before a query is submitted.
    drift = bool(missing)
    reason = None
    if drift:
        reason = "SCJ megaconsulta no longer satisfies the deterministic landing-page contract"
    return SourceSurfaceObservation(
        surface="scj_megaconsulta",
        url=SCJ_MEGAQUERY_URL,
        status="source_drift" if drift else "healthy",
        html_sha256=_digest_html(html),
        byte_count=len(html.encode("utf-8", errors="replace")),
        discovered_item_count=len(discovered),
        missing_markers=missing,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class BrowserRecoveryRequest:
    """Evidence package handed to a browser-capable recovery agent after deterministic drift."""

    observation: SourceSurfaceObservation
    objective: str = (
        "Inspect the official page with Playwright, identify what changed, and propose a new "
        "deterministic source contract. Do not mutate production selectors or download rules."
    )

    def to_json(self) -> str:
        return json.dumps(
            {"observation": asdict(self.observation), "objective": self.objective},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
