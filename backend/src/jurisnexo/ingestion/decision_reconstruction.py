from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jurisnexo.ingestion.document_environment import DocumentEnvironment

Readability = Literal["readable", "empty_source_page"]


def _empty_regions() -> list[UnresolvedSourceRegion]:
    return []


class DecisionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_view_page: int = Field(ge=1)
    end_view_page: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> DecisionBoundary:
        if self.end_view_page < self.start_view_page:
            raise ValueError("end_view_page must be >= start_view_page")
        return self


class DecisionPageSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_page: int = Field(ge=1)
    printed_page: int | None = Field(default=None, ge=1)
    source_reference: str | None = None
    text: str
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(ge=0)
    readability: Readability

    @model_validator(mode="after")
    def validate_span(self) -> DecisionPageSpan:
        if self.char_start != 0:
            raise ValueError("full-page reconstruction must begin at char_start 0")
        if self.char_end != len(self.text):
            raise ValueError("char_end must equal the stored page text length")
        return self


class UnresolvedSourceRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_page: int = Field(ge=1)
    printed_page: int | None = Field(default=None, ge=1)
    source_reference: str | None = None
    reason: Literal["empty_source_page"]
    explanation: str


class SourceFaithfulDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary: DecisionBoundary
    pages: list[DecisionPageSpan]
    page_joiner: Literal["\n\n"] = "\n\n"
    ordered_text: str
    unresolved_regions: list[UnresolvedSourceRegion] = Field(default_factory=_empty_regions)

    @model_validator(mode="after")
    def validate_reconstruction(self) -> SourceFaithfulDecision:
        expected_pages = list(
            range(self.boundary.start_view_page, self.boundary.end_view_page + 1)
        )
        actual_pages = [page.view_page for page in self.pages]
        if actual_pages != expected_pages:
            raise ValueError("pages must cover the decision boundary exactly and in order")
        reconstructed = self.page_joiner.join(page.text for page in self.pages)
        if self.ordered_text != reconstructed:
            raise ValueError("ordered_text must be derived exactly from page spans")
        return self


def reconstruct_source_faithful_decision(
    *,
    environment: DocumentEnvironment,
    boundary: DecisionBoundary,
) -> SourceFaithfulDecision:
    """Reconstruct exactly the bounded source pages without LLM rewriting or neighbor leakage."""

    pages: list[DecisionPageSpan] = []
    unresolved_regions: list[UnresolvedSourceRegion] = []
    for view_page in range(boundary.start_view_page, boundary.end_view_page + 1):
        page = environment.get_full_page(view_page)
        readability: Readability = "readable" if page.text.strip() else "empty_source_page"
        pages.append(
            DecisionPageSpan(
                view_page=view_page,
                printed_page=page.printed_page_number,
                source_reference=page.source_reference,
                text=page.text,
                char_end=len(page.text),
                readability=readability,
            )
        )
        if readability == "empty_source_page":
            unresolved_regions.append(
                UnresolvedSourceRegion(
                    view_page=view_page,
                    printed_page=page.printed_page_number,
                    source_reference=page.source_reference,
                    reason="empty_source_page",
                    explanation=(
                        "The stored source page contains no readable text; reconstruction "
                        "preserves the gap instead of inventing content."
                    ),
                )
            )

    ordered_text = "\n\n".join(page.text for page in pages)
    return SourceFaithfulDecision(
        boundary=boundary,
        pages=pages,
        ordered_text=ordered_text,
        unresolved_regions=unresolved_regions,
    )
