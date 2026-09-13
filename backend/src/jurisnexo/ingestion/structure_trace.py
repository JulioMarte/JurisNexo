from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArtifactInspectionProfile(BaseModel):
    """Deterministic artifact facts exposed to the Structure Agent as evidence."""

    model_config = ConfigDict(extra="forbid")

    media_type: str = "application/pdf"
    physical_page_count: int = Field(ge=1)
    pages_with_extractable_text: int = Field(ge=0)
    pages_with_images: int | None = Field(default=None, ge=0)
    pages_with_text_and_images: int | None = Field(default=None, ge=0)
    suspected_rendering_mode: Literal[
        "born_digital_text",
        "scanned_image",
        "scanned_image_with_text_layer",
        "mixed",
        "unknown",
    ] = "unknown"
    profile_method: str
    notes: list[str] = Field(default_factory=list)


class StructureToolTraceEvent(BaseModel):
    """One deterministic record of a document-inspection tool invocation."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    tool_name: str
    arguments: dict[str, int | str]
    status: Literal["success", "error"]
    result_char_count: int = Field(ge=0)
    result_sha256: str | None = None
    result_excerpt: str = ""
    error_type: str | None = None
    error_message: str | None = None


class StructureToolTraceRecorder:
    """In-memory trace recorder intentionally independent from provider/SDK internals."""

    def __init__(self, *, excerpt_chars: int = 2_000) -> None:
        if excerpt_chars < 200:
            raise ValueError("excerpt_chars must be at least 200")
        self._excerpt_chars = excerpt_chars
        self._events: list[StructureToolTraceEvent] = []

    @property
    def events(self) -> tuple[StructureToolTraceEvent, ...]:
        return tuple(self._events)

    def record_success(
        self,
        *,
        tool_name: str,
        arguments: dict[str, int | str],
        result: str,
    ) -> None:
        encoded = result.encode("utf-8", errors="replace")
        self._events.append(
            StructureToolTraceEvent(
                sequence=len(self._events) + 1,
                tool_name=tool_name,
                arguments=arguments,
                status="success",
                result_char_count=len(result),
                result_sha256=hashlib.sha256(encoded).hexdigest(),
                result_excerpt=result[: self._excerpt_chars],
            )
        )

    def record_error(
        self,
        *,
        tool_name: str,
        arguments: dict[str, int | str],
        error: Exception,
    ) -> None:
        self._events.append(
            StructureToolTraceEvent(
                sequence=len(self._events) + 1,
                tool_name=tool_name,
                arguments=arguments,
                status="error",
                result_char_count=0,
                error_type=type(error).__name__,
                error_message=str(error),
            )
        )


def render_artifact_profile(profile: ArtifactInspectionProfile | None) -> str:
    if profile is None:
        return (
            "No deterministic artifact-rendering profile is available. "
            "Do not infer image/text composition from absence of profile evidence."
        )
    return profile.model_dump_json(indent=2)


def render_tool_trace(
    events: tuple[StructureToolTraceEvent, ...],
    *,
    max_chars: int = 40_000,
) -> str:
    """Render a bounded trace without dropping call identity or result digests."""

    if max_chars < 2_000:
        raise ValueError("max_chars must be at least 2000")
    if not events:
        return "(no document-inspection tool calls were recorded)"

    rendered: list[str] = []
    used = 0
    for event in events:
        chunk = event.model_dump_json(indent=2)
        if used + len(chunk) > max_chars:
            remaining = len(events) - len(rendered)
            rendered.append(f"... trace truncated; {remaining} event(s) omitted from prompt ...")
            break
        rendered.append(chunk)
        used += len(chunk)
    return "\n\n".join(rendered)
