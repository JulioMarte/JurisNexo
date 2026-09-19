from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urljoin, urlparse

from jurisnexo.observability import acquisition_span, span_event

SourceName = Literal["supreme_court", "constitutional_court"]

TC_SENTENCES_URL = (
    "https://www.tribunalconstitucional.gob.do/consultas/secretar%C3%ADa/"
    "sentencias?order=RelativeTo_desc&searchCriteria=&searchString=&size=999999"
)
SCJ_MEGAQUERY_URL = "https://transparencia.poderjudicial.gob.do/consultasSCJ/megaconsulta"
SCJ_PRINCIPALES_URL = (
    "https://poderjudicial.gob.do/suprema-corte-de-justicia/"
    "secretaria-general/principales-sentencias/"
)
_SOURCE_STORAGE_CODES: dict[SourceName, str] = {
    "supreme_court": "scj",
    "constitutional_court": "tc",
}
_COLLECTION_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class OfficialDocumentCandidate:
    source: SourceName
    source_identifier: str
    discovery_url: str
    document_url: str
    collection: str = "decisions"


@dataclass(frozen=True, slots=True)
class StoredOfficialArtifact:
    candidate: OfficialDocumentCandidate
    sha256: str
    byte_count: int
    object_key: str
    already_present: bool


class HttpFetcher(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


@runtime_checkable
class FileDownloadingFetcher(Protocol):
    def download_to_file(self, url: str, destination: Path) -> None: ...


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


@runtime_checkable
class FileObjectStore(Protocol):
    def put_file(
        self,
        *,
        key: str,
        path: Path,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...


class ArtifactCatalog(Protocol):
    def register(self, artifact: StoredOfficialArtifact) -> object: ...


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



def discover_scj_principales_candidates_from_html(
    *, html: str, page_url: str = SCJ_PRINCIPALES_URL
) -> tuple[OfficialDocumentCandidate, ...]:
    """Extract official SCJ Principales compilation PDFs in publisher page order.

    Identity is deliberately conservative: the publisher PDF URL is hashed rather than inferring
    a case/year identity from editorial labels that may change over time.
    """

    allowed_hosts = {"poderjudicial.gob.do", "www.poderjudicial.gob.do"}
    candidates: list[OfficialDocumentCandidate] = []
    seen_urls: set[str] = set()
    for anchor in _anchors(html):
        label = " ".join(anchor.text.split())
        folded_label = label.casefold()
        if "principales" not in folded_label or not (
            "sentenc" in folded_label or "decision" in folded_label
        ):
            continue

        absolute = urljoin(page_url, anchor.href)
        parsed = urlparse(absolute)
        if (parsed.hostname or "").casefold() not in allowed_hosts:
            continue
        if not parsed.path.casefold().endswith(".pdf"):
            continue
        if absolute in seen_urls:
            continue
        seen_urls.add(absolute)
        identifier = "principales-url:" + hashlib.sha256(absolute.encode("utf-8")).hexdigest()
        candidates.append(
            OfficialDocumentCandidate(
                source="supreme_court",
                source_identifier=identifier,
                discovery_url=page_url,
                document_url=absolute,
                collection="principales-sentencias",
            )
        )
    return tuple(candidates)


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
            collection="decisions",
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
                collection="decisions",
            )
        )
    return tuple(candidates)


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def object_key_for(*, source: SourceName, sha256: str, collection: str = "decisions") -> str:
    """Return the stable jurisdiction/source/collection content-addressed object key."""

    if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
        raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")
    if not _COLLECTION_RE.fullmatch(collection):
        raise ValueError("collection must be a lowercase kebab-case storage segment")
    source_code = _SOURCE_STORAGE_CODES[source]
    return f"jurisdictions/do/{source_code}/{collection}/{sha256[:2]}/{sha256}.pdf"


def _materialize_document(
    *,
    fetcher: HttpFetcher,
    url: str,
    destination: Path,
) -> None:
    if isinstance(fetcher, FileDownloadingFetcher):
        fetcher.download_to_file(url, destination)
        return
    destination.write_bytes(fetcher.get_bytes(url))


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def acquire_candidates(
    *,
    candidates: tuple[OfficialDocumentCandidate, ...],
    fetcher: HttpFetcher,
    object_store: ObjectStore,
    artifact_catalog: ArtifactCatalog | None = None,
) -> tuple[StoredOfficialArtifact, ...]:
    """Download to disk, hash exact bytes, content-address, deduplicate, and persist PDFs."""

    seen_urls: set[str] = set()
    results: list[StoredOfficialArtifact] = []
    with acquisition_span("acquisition.batch", candidate_count=len(candidates)) as batch_span:
        for candidate in candidates:
            if candidate.document_url in seen_urls:
                span_event(
                    "candidate.duplicate_url_skipped",
                    source=candidate.source,
                    source_identifier=candidate.source_identifier,
                )
                continue
            seen_urls.add(candidate.document_url)
            host = urlparse(candidate.document_url).hostname or ""
            with (
                acquisition_span(
                    "acquisition.artifact",
                    source=candidate.source,
                    source_identifier=candidate.source_identifier,
                    collection=candidate.collection,
                    **{"server.address": host},
                ) as artifact_span,
                TemporaryDirectory(prefix="jurisnexo-acquisition-") as temp_dir,
            ):
                document_path = Path(temp_dir) / "document.pdf"
                with acquisition_span("acquisition.download"):
                    _materialize_document(
                        fetcher=fetcher,
                        url=candidate.document_url,
                        destination=document_path,
                    )
                with document_path.open("rb") as stream:
                    if stream.read(4) != b"%PDF":
                        raise ValueError(
                            f"official document is not a PDF: {candidate.document_url}"
                        )

                with acquisition_span("acquisition.hash") as hash_span:
                    digest, byte_count = _sha256_file(document_path)
                    hash_span.set_attribute("artifact.byte_count", byte_count)
                    hash_span.set_attribute("artifact.sha256_prefix", digest[:12])

                key = object_key_for(
                    source=candidate.source,
                    collection=candidate.collection,
                    sha256=digest,
                )
                with acquisition_span("acquisition.object_store.head", object_key=key):
                    already_present = object_store.exists(key)
                if not already_present:
                    metadata = {
                        "source": candidate.source,
                        "collection": candidate.collection,
                        "source_identifier": candidate.source_identifier,
                        "source_url": candidate.document_url,
                        "sha256": digest,
                    }
                    with acquisition_span(
                        "acquisition.object_store.put",
                        object_key=key,
                        byte_count=byte_count,
                    ):
                        if isinstance(object_store, FileObjectStore):
                            object_store.put_file(
                                key=key,
                                path=document_path,
                                content_type="application/pdf",
                                metadata=metadata,
                            )
                        else:
                            object_store.put(
                                key=key,
                                content=document_path.read_bytes(),
                                content_type="application/pdf",
                                metadata=metadata,
                            )

                artifact = StoredOfficialArtifact(
                    candidate=candidate,
                    sha256=digest,
                    byte_count=byte_count,
                    object_key=key,
                    already_present=already_present,
                )
                if artifact_catalog is not None:
                    with acquisition_span("acquisition.catalog.register"):
                        artifact_catalog.register(artifact)
                artifact_span.set_attribute("artifact.byte_count", byte_count)
                artifact_span.set_attribute("artifact.sha256_prefix", digest[:12])
                artifact_span.set_attribute("artifact.already_present", already_present)
                results.append(artifact)

        batch_span.set_attribute("acquisition.completed_count", len(results))
    return tuple(results)
