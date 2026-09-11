from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SampleStrategy = Literal["head", "tail", "even"]


@dataclass(frozen=True, slots=True)
class PageView:
    page_number: int
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class TextSearchHit:
    page_number: int
    snippet: str


class DocumentEnvironmentError(ValueError):
    """Raised when a discovery tool request is invalid for the document environment."""


@dataclass(frozen=True, slots=True)
class DocumentEnvironment:
    pages: tuple[str, ...]
    max_page_chars: int = 12_000

    def __post_init__(self) -> None:
        if not self.pages:
            raise DocumentEnvironmentError("document environment requires at least one page")
        if self.max_page_chars < 500:
            raise DocumentEnvironmentError("max_page_chars must be at least 500")

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def get_page(self, page_number: int) -> PageView:
        self._validate_page_number(page_number)
        text = self.pages[page_number - 1]
        clipped, truncated = self._clip(text)
        return PageView(page_number=page_number, text=clipped, truncated=truncated)

    def get_pages(self, start_page: int, end_page: int, *, max_pages: int = 8) -> tuple[PageView, ...]:
        if start_page > end_page:
            raise DocumentEnvironmentError("start_page must be <= end_page")
        self._validate_page_number(start_page)
        self._validate_page_number(end_page)
        if max_pages < 1:
            raise DocumentEnvironmentError("max_pages must be positive")
        requested = end_page - start_page + 1
        if requested > max_pages:
            raise DocumentEnvironmentError(
                f"requested {requested} pages; tool limit is {max_pages} pages per call"
            )
        return tuple(self.get_page(page_number) for page_number in range(start_page, end_page + 1))

    def search_text(
        self,
        query: str,
        *,
        max_hits: int = 20,
        context_chars: int = 120,
    ) -> tuple[TextSearchHit, ...]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            raise DocumentEnvironmentError("search query must not be empty")
        if len(normalized_query) > 200:
            raise DocumentEnvironmentError("search query exceeds 200 characters")
        if max_hits < 1 or max_hits > 100:
            raise DocumentEnvironmentError("max_hits must be between 1 and 100")

        hits: list[TextSearchHit] = []
        for page_number, text in enumerate(self.pages, start=1):
            folded = text.casefold()
            offset = folded.find(normalized_query)
            if offset < 0:
                continue
            start = max(0, offset - context_chars)
            end = min(len(text), offset + len(query) + context_chars)
            snippet = " ".join(text[start:end].split())
            hits.append(TextSearchHit(page_number=page_number, snippet=snippet))
            if len(hits) >= max_hits:
                break
        return tuple(hits)

    def sample_pages(self, strategy: SampleStrategy, count: int) -> tuple[PageView, ...]:
        if count < 1:
            raise DocumentEnvironmentError("sample count must be positive")
        count = min(count, self.page_count)

        if strategy == "head":
            page_numbers = list(range(1, count + 1))
        elif strategy == "tail":
            page_numbers = list(range(self.page_count - count + 1, self.page_count + 1))
        elif strategy == "even":
            page_numbers = self._even_page_numbers(count)
        else:
            raise DocumentEnvironmentError(f"unsupported sample strategy: {strategy}")

        return tuple(self.get_page(page_number) for page_number in page_numbers)

    def describe(self) -> str:
        non_empty_pages = sum(1 for page in self.pages if page.strip())
        total_chars = sum(len(page) for page in self.pages)
        return (
            f"page_count={self.page_count}; non_empty_pages={non_empty_pages}; "
            f"total_text_characters={total_chars}"
        )

    def _validate_page_number(self, page_number: int) -> None:
        if page_number < 1 or page_number > self.page_count:
            raise DocumentEnvironmentError(
                f"page_number {page_number} is outside 1..{self.page_count}"
            )

    def _clip(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_page_chars:
            return text, False
        return text[: self.max_page_chars], True

    def _even_page_numbers(self, count: int) -> list[int]:
        if count == 1:
            return [1]
        if count >= self.page_count:
            return list(range(1, self.page_count + 1))

        page_numbers = {
            1 + round(index * (self.page_count - 1) / (count - 1)) for index in range(count)
        }
        return sorted(page_numbers)
