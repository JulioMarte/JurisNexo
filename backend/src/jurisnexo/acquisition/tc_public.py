from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class TcDecisionArtifact:
    detail_url: str
    document_url: str
    filename: str
    content: bytes
    sha256: str
    content_type: str


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() not in {"a", "iframe"}:
            return
        for name, value in attrs:
            if name.casefold() not in {"href", "src"} or value is None:
                continue
            if ".pdf" in value.casefold():
                self.hrefs.append(value)


def discover_tc_pdf_url(
    *,
    detail_html: str,
    detail_url: str,
    expected_filename: str | None = None,
) -> str:
    parser = _PdfLinkParser()
    parser.feed(detail_html)
    candidates = tuple(
        dict.fromkeys(urljoin(detail_url, href) for href in parser.hrefs)
    )
    if expected_filename is not None:
        exact = tuple(
            url for url in candidates
            if url.casefold().endswith(expected_filename.casefold())
        )
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ValueError("TC detail page exposes duplicate matching PDF links")
    if len(candidates) != 1:
        raise ValueError(
            f"expected one TC decision PDF link, found {len(candidates)}"
        )
    return candidates[0]


def fetch_tc_decision(
    *,
    detail_url: str,
    expected_filename: str | None = None,
    timeout_seconds: float = 30.0,
) -> TcDecisionArtifact:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    detail_request = Request(
        detail_url,
        headers={"User-Agent": "JurisNexo/normalization-proof"},
    )
    with urlopen(detail_request, timeout=timeout_seconds) as response:
        detail_html = response.read().decode("utf-8", errors="replace")

    document_url = discover_tc_pdf_url(
        detail_html=detail_html,
        detail_url=detail_url,
        expected_filename=expected_filename,
    )
    document_request = Request(
        document_url,
        headers={"User-Agent": "JurisNexo/normalization-proof"},
    )
    with urlopen(document_request, timeout=timeout_seconds) as response:
        content = response.read()
        content_type = response.headers.get_content_type()

    if not content.startswith(b"%PDF-"):
        raise ValueError("TC official document response is not a PDF")
    filename = document_url.rstrip("/").rsplit("/", 1)[-1]
    return TcDecisionArtifact(
        detail_url=detail_url,
        document_url=document_url,
        filename=filename,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        content_type=content_type or "application/pdf",
    )
