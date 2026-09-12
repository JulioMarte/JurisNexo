from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    acquire_candidates,
    discover_scj_pdf_candidates_from_html,
    discover_tc_detail_pages,
    object_key_for,
    sha256_hex,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


@dataclass(slots=True)
class FakeFetcher:
    payloads: dict[str, bytes]
    calls: list[str] = field(default_factory=list)

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        return self.payloads[url]


@dataclass(slots=True)
class MemoryObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)
    puts: int = 0

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        assert content_type == "application/pdf"
        assert metadata["sha256"] == sha256_hex(content)
        self.objects[key] = content
        self.puts += 1


def test_tc_listing_parser_keeps_only_official_sentence_detail_links() -> None:
    html = """
    <a href="/consultas/secretaría/sentencias/tc000126">TC/0001/26</a>
    <a href="https://evil.example/tc000226">TC/0002/26</a>
    <a href="/noticias/foo">TC/0003/26</a>
    """

    results = discover_tc_detail_pages(
        html=html,
        listing_url="https://www.tribunalconstitucional.gob.do/consultas/secretaría/sentencias",
    )

    assert results == (
        (
            "TC/0001/26",
            "https://www.tribunalconstitucional.gob.do/consultas/secretaría/sentencias/tc000126",
        ),
    )


def test_scj_parser_keeps_only_same_host_consultas_pdf_links() -> None:
    html = """
    <a href="/consultasSCJ/documentos/pdf/BoletinJudicialIndividual/129120049.pdf">PDF</a>
    <a href="https://transparencia.poderjudicial.gob.do/consultasSCJ/Reportepdf/reporte001.pdf">PDF2</a>
    <a href="https://evil.example/consultasSCJ/fake.pdf">bad</a>
    """

    results = discover_scj_pdf_candidates_from_html(
        html=html,
        page_url="https://transparencia.poderjudicial.gob.do/consultasSCJ/results",
    )

    assert [candidate.source_identifier for candidate in results] == [
        "reporte001",
        "129120049",
    ]
    assert all(candidate.source == "supreme_court" for candidate in results)


def test_acquisition_is_content_addressed_and_idempotent() -> None:
    url = "https://official.example/document.pdf"
    candidate = OfficialDocumentCandidate(
        source="constitutional_court",
        source_identifier="TC/0001/26",
        discovery_url="https://official.example/detail",
        document_url=url,
    )
    pdf = b"%PDF-1.7\nfixture"
    fetcher = FakeFetcher(payloads={url: pdf})
    store = MemoryObjectStore()

    first = acquire_candidates(candidates=(candidate,), fetcher=fetcher, object_store=store)
    second = acquire_candidates(candidates=(candidate,), fetcher=fetcher, object_store=store)

    digest = sha256_hex(pdf)
    expected_key = object_key_for(source="constitutional_court", sha256=digest)
    assert first[0].object_key == expected_key
    assert first[0].already_present is False
    assert second[0].already_present is True
    assert store.puts == 1


def test_duplicate_document_urls_are_downloaded_once_per_loop() -> None:
    url = "https://official.example/document.pdf"
    candidates = tuple(
        OfficialDocumentCandidate(
            source="supreme_court",
            source_identifier=str(index),
            discovery_url="https://official.example/results",
            document_url=url,
        )
        for index in (1, 2)
    )
    fetcher = FakeFetcher(payloads={url: b"%PDF fixture"})
    store = MemoryObjectStore()

    results = acquire_candidates(candidates=candidates, fetcher=fetcher, object_store=store)

    assert len(results) == 1
    assert fetcher.calls == [url]


def test_non_pdf_response_fails_closed_before_bucket_write() -> None:
    url = "https://official.example/document.pdf"
    candidate = OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier="x",
        discovery_url="https://official.example/results",
        document_url=url,
    )
    store = MemoryObjectStore()

    with pytest.raises(ValueError, match="not a PDF"):
        acquire_candidates(
            candidates=(candidate,),
            fetcher=FakeFetcher(payloads={url: b"<html>error</html>"}),
            object_store=store,
        )

    assert store.puts == 0
