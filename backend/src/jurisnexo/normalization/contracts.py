from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class FormatInspection:
    media_type: str
    detected_format: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class NormalizedDocument:
    media_type: str
    payload: bytes
    engine: str
    engine_version: str | None
    metadata: dict[str, Any]


class FormatInspector(Protocol):
    def inspect(self, source: bytes, *, filename: str | None = None) -> FormatInspection: ...


class StructuralNormalizer(Protocol):
    def normalize(
        self, source: bytes, inspection: FormatInspection, *, filename: str | None = None
    ) -> NormalizedDocument: ...


class OcrBackend(Protocol):
    def recognize(self, image: bytes, *, media_type: str) -> str: ...


class TextQualityJudge(Protocol):
    def judge(self, text: str, *, context: dict[str, Any]) -> dict[str, Any]: ...


class VisualTextVerifier(Protocol):
    def verify(self, image: bytes, candidate_text: str, *, context: dict[str, Any]) -> dict[str, Any]: ...


class NormalizedRepresentationResolver(Protocol):
    def resolve(self, candidates: tuple[NormalizedDocument, ...]) -> NormalizedDocument: ...
