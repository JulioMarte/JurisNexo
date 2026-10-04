"""Independent (non-Ling) OCR of adjudication pages via a vision model.

The runner renders a page exactly as the Ling worker did and asks a *different*
vision model, with no candidate text, to transcribe only what is visible. The
result is independent evidence that a later blind adjudication step can compare
against the Ling Pass 1 / Pass 2 disagreement; it is never primary-source truth
and never overwrites the source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

INDEPENDENT_OCR_PROMPT = (
    "Transcribe exactamente todo el texto visible de esta página, en orden de lectura. "
    "Devuelve únicamente la transcripción, sin comentarios, resúmenes ni Markdown. "
    "No corrijas, completes ni inventes texto. Si un fragmento es ilegible, escribe "
    "[ilegible]. Respeta mayúsculas, acentos, puntuación, números, identificadores y "
    "saltos de línea."
)


@dataclass(frozen=True, slots=True)
class OcrTarget:
    document_id: str
    page_index: int
    object_key: str
    source_pdf_sha256: str


@dataclass(frozen=True, slots=True)
class IndependentOcrRecord:
    document_id: str
    page_index: int
    object_key: str
    source_pdf_sha256: str
    render_pixel_sha256: str
    requested_model: str
    provider_tag: str
    returned_model: str
    returned_provider: str
    reasoning_effort: str
    prompt_sha256: str
    transcription: str
    transcription_sha256: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    response_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prompt_sha256(prompt: str = INDEPENDENT_OCR_PROMPT) -> str:
    return sha256_text(prompt)


def shard_targets(
    targets: Sequence[OcrTarget],
    *,
    shard_index: int,
    shard_count: int,
) -> list[OcrTarget]:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    return [
        target
        for position, target in enumerate(targets)
        if position % shard_count == shard_index
    ]


def build_record(
    *,
    target: OcrTarget,
    render_pixel_sha256: str,
    requested_model: str,
    provider_tag: str,
    returned_model: str,
    returned_provider: str,
    reasoning_effort: str,
    transcription: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_usd: float | None,
    response_id: str | None,
) -> IndependentOcrRecord:
    return IndependentOcrRecord(
        document_id=target.document_id,
        page_index=target.page_index,
        object_key=target.object_key,
        source_pdf_sha256=target.source_pdf_sha256,
        render_pixel_sha256=render_pixel_sha256,
        requested_model=requested_model,
        provider_tag=provider_tag,
        returned_model=returned_model,
        returned_provider=returned_provider,
        reasoning_effort=reasoning_effort,
        prompt_sha256=prompt_sha256(),
        transcription=transcription,
        transcription_sha256=sha256_text(transcription),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        response_id=response_id,
    )
