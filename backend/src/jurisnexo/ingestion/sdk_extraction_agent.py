from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agents import Agent, ModelSettings, RunConfig, RunContextWrapper, Runner
from agents.decorators import tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jurisnexo.ingestion.decision_reconstruction import SourceFaithfulDecision

SectionKind = Literal[
    "heading_caption",
    "parties",
    "procedural_history",
    "facts",
    "party_arguments",
    "court_reasoning",
    "dispositive_outcome",
    "signatures_administrative_tail",
]
MetadataField = Literal[
    "court_chamber",
    "decision_date",
    "decision_number",
    "docket_reference",
    "matter_procedure",
    "party",
    "source_citation",
]
ReferenceKind = Literal[
    "statute_article",
    "regulation",
    "cited_decision",
    "institution_document",
]


def _empty_spans() -> list[EvidenceSpan]:
    return []


def _empty_sections() -> list[SectionAnnotation]:
    return []


def _empty_metadata() -> list[MetadataAnnotation]:
    return []


def _empty_references() -> list[ReferenceAnnotation]:
    return []


def _empty_strings() -> list[str]:
    return []


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_page: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    exact_text: str

    @model_validator(mode="after")
    def validate_order(self) -> EvidenceSpan:
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if not self.exact_text:
            raise ValueError("exact_text must not be empty")
        return self


class SectionAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SectionKind
    evidence: list[EvidenceSpan] = Field(default_factory=_empty_spans)
    confidence: float = Field(ge=0.0, le=1.0)


class MetadataAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: MetadataField
    value: str
    evidence: list[EvidenceSpan] = Field(default_factory=_empty_spans)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_support(self) -> MetadataAnnotation:
        if not self.value.strip():
            raise ValueError("metadata value must not be empty")
        if not self.evidence:
            raise ValueError("metadata annotations require source evidence")
        return self


class ReferenceAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReferenceKind
    reference_as_written: str
    evidence: list[EvidenceSpan] = Field(default_factory=_empty_spans)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_support(self) -> ReferenceAnnotation:
        if not self.reference_as_written.strip():
            raise ValueError("reference_as_written must not be empty")
        if not self.evidence:
            raise ValueError("reference annotations require source evidence")
        return self


class ExtractionAnnotations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[SectionAnnotation] = Field(default_factory=_empty_sections)
    metadata: list[MetadataAnnotation] = Field(default_factory=_empty_metadata)
    references: list[ReferenceAnnotation] = Field(default_factory=_empty_references)
    unresolved: list[str] = Field(default_factory=_empty_strings)


@dataclass(frozen=True, slots=True)
class ExtractionAgentContext:
    decision: SourceFaithfulDecision
    max_tool_output_chars: int = 40_000

    def __post_init__(self) -> None:
        if self.max_tool_output_chars < 1_000:
            raise ValueError("max_tool_output_chars must be at least 1000")


@dataclass(frozen=True, slots=True)
class ExtractionAgentRunResult:
    annotations: ExtractionAnnotations
    usage_total_tokens: int
    last_agent_name: str


_INSTRUCTIONS = """\
You are the JurisNexo Extraction Agent. The source-faithful decision reconstruction is immutable.
Do not rewrite, summarize, repair, or complete its text. Your task is only to annotate bounded
source content with structural sections, basic metadata, and references.

Every metadata value and every reference must point to exact source spans. Section labels should
also use source spans when supported. `exact_text` must be copied exactly from the specified page
and character range. Never use evidence outside the bounded decision. Do not infer missing dates,
parties, numbers, holdings, legal issues, or citations. Put uncertain/missing items in `unresolved`
instead of guessing.

Do not perform deep legal enrichment. In particular, do not create holdings, Legal Elements,
proposition graphs, citation treatment, or later-treatment conclusions in this stage.
"""


def render_decision_page(decision: SourceFaithfulDecision, view_page: int) -> str:
    """Render one complete page only when it belongs to the bounded decision."""

    for page in decision.pages:
        if page.view_page == view_page:
            return (
                f"view_page={page.view_page} | printed_page={page.printed_page} | "
                f"source_reference={page.source_reference}\n{page.text}"
            )
    raise ValueError(f"view_page {view_page} is outside the bounded decision")


def search_bounded_decision(decision: SourceFaithfulDecision, query: str) -> str:
    """Search literal text only inside the bounded decision."""

    needle = query.strip()
    if not needle:
        raise ValueError("query must not be empty")
    if len(needle) > 200:
        raise ValueError("query exceeds 200 characters")
    hits: list[str] = []
    folded_needle = needle.casefold()
    for page in decision.pages:
        folded = page.text.casefold()
        start = 0
        while len(hits) < 20:
            offset = folded.find(folded_needle, start)
            if offset < 0:
                break
            end = offset + len(needle)
            hits.append(
                f"view_page={page.view_page} | char_start={offset} | char_end={end}\n"
                f"{page.text[offset:end]}"
            )
            start = max(end, offset + 1)
    return "\n\n".join(hits) if hits else "No literal hits."


def _bound(context: ExtractionAgentContext, output: str) -> str:
    if len(output) > context.max_tool_output_chars:
        raise ValueError("tool output exceeds extraction context budget; narrow the request")
    return output


@tool(failure_error_function=None)
def get_decision_page(ctx: RunContextWrapper[ExtractionAgentContext], view_page: int) -> str:
    """Read one complete source page, but only if it belongs to the bounded decision."""

    return _bound(ctx.context, render_decision_page(ctx.context.decision, view_page))


@tool(failure_error_function=None)
def search_decision_text(ctx: RunContextWrapper[ExtractionAgentContext], query: str) -> str:
    """Find literal text only inside the bounded decision and return page-local character spans."""

    return _bound(ctx.context, search_bounded_decision(ctx.context.decision, query))


def validate_extraction_annotations(
    *, annotations: ExtractionAnnotations, decision: SourceFaithfulDecision
) -> None:
    pages = {page.view_page: page for page in decision.pages}
    spans = [span for item in annotations.sections for span in item.evidence]
    spans.extend(span for item in annotations.metadata for span in item.evidence)
    spans.extend(span for item in annotations.references for span in item.evidence)
    for index, span in enumerate(spans, start=1):
        page = pages.get(span.view_page)
        if page is None:
            raise ValueError(f"evidence span {index} references a page outside the decision")
        if span.char_end > len(page.text):
            raise ValueError(f"evidence span {index} exceeds source page length")
        actual = page.text[span.char_start : span.char_end]
        if actual != span.exact_text:
            raise ValueError(f"evidence span {index} exact_text does not match source")


def build_extraction_agent(*, model: str = "gpt-5.6-luna") -> Agent[ExtractionAgentContext]:
    return Agent[ExtractionAgentContext](
        name="JurisNexo Extraction Agent",
        instructions=_INSTRUCTIONS,
        model=model,
        model_settings=ModelSettings(parallel_tool_calls=False),
        tools=[get_decision_page, search_decision_text],
        output_type=ExtractionAnnotations,
    )


async def run_extraction_agent(
    *,
    decision: SourceFaithfulDecision,
    artifact_label: str,
    model: str = "gpt-5.6-luna",
    max_turns: int = 12,
    max_tool_output_chars: int = 40_000,
) -> ExtractionAgentRunResult:
    context = ExtractionAgentContext(
        decision=decision,
        max_tool_output_chars=max_tool_output_chars,
    )
    agent = build_extraction_agent(model=model)
    boundary = decision.boundary
    prompt = (
        f"Artifact: {artifact_label}\n"
        f"Bounded decision view pages: {boundary.start_view_page}..{boundary.end_view_page}\n"
        f"Unresolved source regions: {len(decision.unresolved_regions)}\n\n"
        "Annotate only this bounded decision. Use tools to obtain exact source spans."
    )
    result = await Runner.run(
        starting_agent=agent,
        input=prompt,
        context=context,
        max_turns=max_turns,
        run_config=RunConfig(
            workflow_name="JurisNexo Decision Extraction",
            trace_include_sensitive_data=False,
        ),
    )
    annotations = result.final_output_as(ExtractionAnnotations, raise_if_incorrect_type=True)
    validate_extraction_annotations(annotations=annotations, decision=decision)
    return ExtractionAgentRunResult(
        annotations=annotations,
        usage_total_tokens=result.context_wrapper.usage.total_tokens,
        last_agent_name=result.last_agent.name,
    )
