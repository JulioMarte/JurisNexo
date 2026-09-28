from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jurisnexo.normalization.resolver import ResolvedEvidenceText


@dataclass(frozen=True, slots=True)
class DocumentPage:
    page_id: str
    physical_index: int
    printed_label: str | None
    evidence: ResolvedEvidenceText


class DocumentWorkspaceBackend(Protocol):
    def pages(self) -> tuple[DocumentPage, ...]: ...
    def structure(self) -> dict[str, object]: ...
    def render_page(self, page_id: str) -> bytes: ...


@dataclass(slots=True)
class DocumentWorkspace:
    """Stable engine-neutral surface exposed to downstream agents."""

    backend: DocumentWorkspaceBackend

    def get_document_structure(self) -> dict[str, object]:
        return self.backend.structure()

    def read_page(self, page_id: str) -> str:
        for page in self.backend.pages():
            if page.page_id == page_id:
                return page.evidence.text
        raise KeyError(page_id)

    def read_pages(self, start: int, end: int) -> tuple[str, ...]:
        if start < 0 or end < start:
            raise ValueError("invalid page range")
        pages = sorted(self.backend.pages(), key=lambda item: item.physical_index)
        return tuple(page.evidence.text for page in pages[start:end])

    def search_document(self, query: str) -> tuple[str, ...]:
        needle = query.casefold().strip()
        if not needle:
            raise ValueError("query must not be empty")
        return tuple(
            page.page_id
            for page in self.backend.pages()
            if needle in page.evidence.text.casefold()
        )

    def render_page_image(self, page_id: str) -> bytes:
        return self.backend.render_page(page_id)

    def get_evidence(self, page_id: str) -> ResolvedEvidenceText:
        for page in self.backend.pages():
            if page.page_id == page_id:
                return page.evidence
        raise KeyError(page_id)
