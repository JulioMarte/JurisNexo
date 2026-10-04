"""RapidOCR visual-reference OCR backend.

RapidOCR (ONNX, PP-OCR family) is the provisionally adopted base OCR engine for
the new SCJ normalization lane, ahead of Tesseract. See
`docs/benchmarks/2026-10-01-scj-hard-rescue-ocr-engine-comparison.md`.

The engine dependency is imported lazily so the backend module stays cheap to
import and testable without the ONNX runtime installed. Parsing is separated from
inference so it can be proven with a hand-authored engine output.
"""

from __future__ import annotations

import importlib
import io
import math
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import Any, cast

from jurisnexo.normalization.visual_reference_ocr import VisualOcrObservation

DEFAULT_LANGUAGE = "es"
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.5


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def parse_rapidocr_output(
    txts: Sequence[object],
    scores: Sequence[object] | None,
    *,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    engine_version: str = "unknown",
    language: str = DEFAULT_LANGUAGE,
) -> VisualOcrObservation:
    """Turn a RapidOCR result into a ``VisualOcrObservation``."""

    texts = [str(item) for item in txts if str(item).strip()]
    confidences: list[float] = []
    for value in scores or ():
        try:
            score = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if score >= 0:
            confidences.append(score)
    word_count = len(texts)
    return VisualOcrObservation(
        text="\n".join(texts),
        mean_confidence=(sum(confidences) / len(confidences)) if confidences else None,
        median_confidence=_percentile(confidences, 0.5),
        p10_confidence=_percentile(confidences, 0.1),
        low_confidence_word_ratio=(
            sum(value < low_confidence_threshold for value in confidences) / len(confidences)
            if confidences
            else None
        ),
        word_count=word_count,
        engine_version=engine_version,
        language=language,
    )


@lru_cache(maxsize=1)
def rapidocr_version() -> str:
    rapidocr = importlib.import_module("rapidocr")

    return str(getattr(rapidocr, "__version__", "unknown"))


def parallel_text_and_scores(result: Any) -> tuple[list[str], list[float] | None]:
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if txts is not None:
        texts = [str(item) for item in cast("list[object]", txts)]
        confidences = (
            [float(str(item)) for item in cast("list[object]", scores)]
            if scores is not None
            else None
        )
        return texts, confidences
    # Older result shape: a list of [box, text, score] rows.
    texts: list[str] = []
    values: list[float] = []
    for row in cast("Iterable[object]", result or ()):
        if not isinstance(row, (list, tuple)):
            continue
        cells = list(cast("Iterable[object]", row))
        if len(cells) < 3:
            continue
        texts.append(str(cells[1]))
        score_cell = cells[2]
        if isinstance(score_cell, (int, float)) and not isinstance(score_cell, bool):
            values.append(float(score_cell))
        else:
            try:
                values.append(float(str(score_cell)))
            except ValueError:
                values.append(0.0)
    return texts, (values or None)


def run_rapidocr_visual_ocr(
    image: bytes,
    *,
    language: str = DEFAULT_LANGUAGE,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> VisualOcrObservation:
    numpy = importlib.import_module("numpy")
    pil_image = importlib.import_module("PIL.Image")
    rapidocr = importlib.import_module("rapidocr")

    ocr = rapidocr.RapidOCR()
    with pil_image.open(io.BytesIO(image)) as opened:
        array = numpy.asarray(opened.convert("RGB"))
    result = ocr(array)
    txts, scores = parallel_text_and_scores(result)
    return parse_rapidocr_output(
        txts,
        scores,
        low_confidence_threshold=low_confidence_threshold,
        engine_version=rapidocr_version(),
        language=language,
    )
