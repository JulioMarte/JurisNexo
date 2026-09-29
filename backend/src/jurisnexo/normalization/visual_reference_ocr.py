from __future__ import annotations

import csv
import io
import math
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class TesseractTsvObservation:
    text: str
    mean_confidence: float | None
    median_confidence: float | None
    p10_confidence: float | None
    low_confidence_word_ratio: float | None
    word_count: int


@dataclass(frozen=True, slots=True)
class VisualOcrObservation:
    text: str
    mean_confidence: float | None
    engine_version: str
    language: str
    median_confidence: float | None = None
    p10_confidence: float | None = None
    low_confidence_word_ratio: float | None = None
    word_count: int = 0


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


def parse_tesseract_tsv_observation(
    tsv_text: str,
    *,
    low_confidence_threshold: float = 80.0,
) -> TesseractTsvObservation:
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    lines: list[str] = []
    current_line: tuple[str, str, str, str] | None = None
    words: list[str] = []
    confidences: list[float] = []
    word_count = 0

    def flush_line() -> None:
        if words:
            lines.append(" ".join(words))
            words.clear()

    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        line_key = (
            row.get("page_num") or "",
            row.get("block_num") or "",
            row.get("par_num") or "",
            row.get("line_num") or "",
        )
        if current_line is not None and line_key != current_line:
            flush_line()
        current_line = line_key
        words.append(text)
        word_count += 1
        try:
            confidence = float(row.get("conf") or "-1")
        except ValueError:
            confidence = -1.0
        if confidence >= 0:
            confidences.append(confidence)

    flush_line()
    mean_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else None
    )
    median_confidence = _percentile(confidences, 0.5)
    p10_confidence = _percentile(confidences, 0.1)
    low_confidence_word_ratio = (
        sum(value < low_confidence_threshold for value in confidences)
        / len(confidences)
        if confidences
        else None
    )
    return TesseractTsvObservation(
        text="\n".join(lines),
        mean_confidence=mean_confidence,
        median_confidence=median_confidence,
        p10_confidence=p10_confidence,
        low_confidence_word_ratio=low_confidence_word_ratio,
        word_count=word_count,
    )


def parse_tesseract_tsv(tsv_text: str) -> tuple[str, float | None]:
    observation = parse_tesseract_tsv_observation(tsv_text)
    return observation.text, observation.mean_confidence


@lru_cache(maxsize=1)
def tesseract_version() -> str:
    result = subprocess.run(
        ["tesseract", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("tesseract is required for visual-reference admission")
    lines = (result.stdout or result.stderr).splitlines()
    return lines[0] if lines else "tesseract unknown"


def run_tesseract_visual_ocr(
    image: bytes,
    *,
    language: str = "spa+eng",
    page_segmentation_mode: int = 6,
) -> VisualOcrObservation:
    with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
        temporary.write(image)
        temporary.flush()
        result = subprocess.run(
            [
                "tesseract",
                temporary.name,
                "stdout",
                "-l",
                language,
                "--psm",
                str(page_segmentation_mode),
                "tsv",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or "tesseract failed"
        raise RuntimeError(detail)
    observation = parse_tesseract_tsv_observation(result.stdout)
    return VisualOcrObservation(
        text=observation.text,
        mean_confidence=observation.mean_confidence,
        median_confidence=observation.median_confidence,
        p10_confidence=observation.p10_confidence,
        low_confidence_word_ratio=observation.low_confidence_word_ratio,
        word_count=observation.word_count,
        engine_version=tesseract_version(),
        language=language,
    )
