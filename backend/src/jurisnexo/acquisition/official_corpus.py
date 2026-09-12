from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import urljoin, urlparse

SourceName = Literal["supreme_court", "constitutional_court"]

TC_SENTENCES_URL = (
    "https://www.tribunalconstitucional.gob.do/consultas/secretar%C3%ADa/"
    "sentencias?order=RelativeTo_desc&searchCriteria=&searchString=&size=999999"
)
SCJ_MEGAQUERY_URL = "https://transparencia.poderjudicial.gob.do/consultasSCJ/megaconsulta"


@dataclass(frozen=True, slots=True)
class OfficialDocumentCandidate:
    source: SourceName
    source_identifier: str
    discovery_url: str
    document_url: str


@dataclass(frozen=True, slots=True)
class StoredOfficialArtifact:
    candidate: OfficialDocumentCandidate
    sha256: str
    byte_count: int
    object_key: str
    already_present: bool


class HttpFetcher(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


class ObjectStore(Protocol):
    def exists(self, key: str) -> bool: ...

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _Anchor:
    href: str
    text: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        text = " ".join("".join(self._text_parts).split())
        self.anchors.append(_Anchor(href=self._href, text=text))
        self._href = None
        self._text_parts = []


def _anchors(html: str) -> tuple[_Anchor, ...]:
    parser = _AnchorParser()
    parser.feed(html)
    parser.close()
    return tuple(parser.anchors)


def _same_host(url: str, expected_host: str) -> bool:
    return urlparse(url).hostname == expected_host


def discover_tc_detail_pages(*, html: str, listing_url: str) -> tuple[tuple[str, str], ...]:
    """Return stable `(sentence_id, detail_url)` pairs from the official TC listing."""

    results: dict[str, str] = {}
    for anchor in _anchors(html):
        sentence_id = anchor.text.strip().upper()
        if not sentence_id.startswith("TC/"):
            continue
        absolute = urljoin(listing_url, anchor.href)
        if not _same_host(absolute, "www.tribunalconstitucional.gob.do"):
            continue
        path = urlparse(absolute).path.casefold()
        if "/consultas/secretar" not in path or "/sentencias/" not in path:
            continue
        results[sentence_id] = absolute
    return tuple(sorted(results.items()))


def discover_pdf_link(*, html: str, page_url: str, allowed_host: str) -> str:
    """Find one same-host PDF link from an official detail/result page."""

    pdfs: list[str] = []
    for anchor in _anchors(html):
        absolute = urljoin(page_url, anchor.href)
        if not _same_host(absolute, allowed_host):
            continue
        if urlparse(absolute).path.casefold().endswith(".pdf"):
            pdfs.append(absolute)
    unique = sorted(set(pdfs))
    if len(unique) != 1:
        raise ValueError(f"expected exactly one official PDF link, found {len(unique)}")
    return unique[0]


def discover_scj_pdf_candidates_from_html(
    *, html: str, page_url: str
) -> tuple[OfficialDocumentCandidate, ...]:
    """Extract direct SCJ PDFs from a megaconsulta/result HTML snapshot."""

    candidates: dict[str, OfficialDocumentCandidate] = {}
    for anchor in _anchors(html):
        absolute = urljoin(page_url, anchor.href)
        if not _same_host(absolute, "transparencia.poderjudicial.gob.do"):
            continue
        path = urlparse(absolute).path
        folded = path.casefold()
        if not folded.endswith(".pdf") or "/consultasscj/" not in folded:
            continue
        identifier = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        candidates[absolute] = OfficialDocumentCandidate(
            source="supreme_court",
            source_identifier=identifier,
            discovery_url=page_url,
            document_url=absolute,
        )
    return tuple(candidates[url] for url in sorted(candidates))


def crawl_tc_candidates(fetcher: HttpFetcher) -> tuple[OfficialDocumentCandidate, ...]:
    listing_html = fetcher.get_bytes(TC_SENTENCES_URL).decode("utf-8", errors="replace")
    candidates: list[OfficialDocumentCandidate] = []
    for sentence_id, detail_url in discover_tc_detail_pages(
        html=listing_html,
        listing_url=TC_SENTENCES_URL,
    ):
        detail_html = fetcher.get_bytes(detail_url).decode("utf-8", errors="replace")
        document_url = discover_pdf_link(
            html=detail_html,
            page_url=detail_url,
            allowed_host="tribunalsitestorage.blob.core.windows.net",
        )
        candidates.append(
            OfficialDocumentCandidate(
                source="constitutional_court",
                source_identifier=sentence_id,
                discovery_url=detail_url,
                document_url=document_url,
            )
        )
    return tuple(candidates)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def object_key_for(*, source: SourceName, sha256: str) -> str:
    if len(sha256) != 64:
        raise ValueError("sha256 must be a 64-character hexadecimal digest")
    return f"official/{source}/{sha256[:2]}/{sha256}.pdf"


def acquire_candidates(
    *,
    candidates: tuple[OfficialDocumentCandidate, ...],
    fetcher: HttpFetcher,
    object_store: ObjectStore,
) -> tuple[StoredOfficialArtifact, ...]:
    """Download and content-address official PDFs idempotently."""

    seen_urls: set[str] = set()
    results: list[StoredOfficialArtifact] = []
    for candidate in candidates:
        if candidate.document_url in seen_urls:
            continue
        seen_urls.add(candidate.document_url)
        content = fetcher.get_bytes(candidate.document_url)
        if not content.startswith(b"%PDF"):
            raise ValueError(f"official document is not a PDF: {candidate.document_url}")
        digest = sha256_hex(content)
        key = object_key_for(source=candidate.source, sha256=digest)
        already_present = object_store.exists(key)
        if not already_present:
            object_store.put(
                key=key,
                content=content,
                content_type="application/pdf",
                metadata={
                    "source": candidate.source,
                    "source_identifier": candidate.source_identifier,
                    "source_url": candidate.document_url,
                    "sha256": digest,
                },
            )
        results.append(
            StoredOfficialArtifact(
                candidate=candidate,
                sha256=digest,
                byte_count=len(content),
                object_key=key,
                already_present=already_present,
            )
        )
    return tuple(results)
