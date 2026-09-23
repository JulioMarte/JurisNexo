from __future__ import annotations

from dataclasses import dataclass

# Compiled Principales volumes begin with cover, credits, ISBN and library
# catalog-card front matter and one or more tables of contents. Selecting the
# first page with enough native text therefore samples bibliographic front
# matter, never a judgment, and cannot measure legal-document normalization.
# These markers reject such pages so the benchmarks measure adjudicative text.
FRONT_MATTER_MARKERS: tuple[str, ...] = (
    "isbn",
    "coordinación general",
    "1a. ed.",
    "r426p",
    "índice",
    "indice",
    "impreso en",
    "www.poderjudicial.gob.do",
    "diagramación",
    "división de publicaciones",
    "división de jurisprudencia",
    "catalogación",
    "ejemplares",
)

# pypdfium2 emits U+FFFE for glyphs it cannot decode (frequently a line-break
# hyphen). Removing it avoids charging a reference artifact to the candidate as
# a fidelity error.
NATIVE_ARTIFACT = "\ufffe"


@dataclass(frozen=True, slots=True)
class ReferencePage:
    page_index: int
    document_page_count: int
    text: str


def normalize_native_reference(text: str) -> str:
    return text.replace(NATIVE_ARTIFACT, "").strip()


def looks_like_body_page(text: str) -> bool:
    folded = text.casefold()
    if any(marker in folded for marker in FRONT_MATTER_MARKERS):
        return False
    if folded.count("considerando") >= 2:
        return True
    if "en nombre de la república" in folded:
        return True
    return "vistos" in folded and ("falla" in folded or "fallamos" in folded)


def has_native_text(pdf_bytes: bytes, probe_pages: int = 3) -> bool:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for page_index in range(min(len(document), probe_pages)):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    if len(text_page.get_text_range().strip()) >= 200:
                        return True
                finally:
                    text_page.close()
            finally:
                page.close()
    finally:
        document.close()
    return False


def select_reference_page(
    pdf_bytes: bytes,
    *,
    min_reference_chars: int,
    max_pages_to_scan: int,
) -> ReferencePage | None:
    pages = select_reference_pages(
        pdf_bytes,
        min_reference_chars=min_reference_chars,
        max_pages_to_scan=max_pages_to_scan,
        max_pages_per_document=1,
    )
    return pages[0] if pages else None


def select_reference_pages(
    pdf_bytes: bytes,
    *,
    min_reference_chars: int,
    max_pages_to_scan: int,
    max_pages_per_document: int,
) -> tuple[ReferencePage, ...]:
    """Select up to ``max_pages_per_document`` judgment pages, spread out.

    Sampling more than the first qualifying page reduces the selection bias of
    "first clean page" and lets callers measure document-level worst-case
    fidelity. The selected pages are spread across the qualifying range so the
    document is not represented only by its opening page.
    """

    if max_pages_per_document < 1:
        raise ValueError("max_pages_per_document must be at least 1")

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page_count = len(document)
        page_limit = min(page_count, max_pages_to_scan)
        candidates: list[ReferencePage] = []
        for page_index in range(page_limit):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    reference = normalize_native_reference(
                        text_page.get_text_range()
                    )
                finally:
                    text_page.close()
                if len(reference) < min_reference_chars:
                    continue
                if not looks_like_body_page(reference):
                    continue
                candidates.append(
                    ReferencePage(
                        page_index=page_index,
                        document_page_count=page_count,
                        text=reference,
                    )
                )
            finally:
                page.close()
    finally:
        document.close()

    if len(candidates) <= max_pages_per_document:
        return tuple(candidates)
    if max_pages_per_document == 1:
        return (candidates[0],)
    step = (len(candidates) - 1) / (max_pages_per_document - 1)
    indices = sorted(
        {round(step * offset) for offset in range(max_pages_per_document)}
    )
    return tuple(candidates[index] for index in indices)
