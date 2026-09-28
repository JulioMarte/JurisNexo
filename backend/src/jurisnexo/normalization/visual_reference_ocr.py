from __future__ import annotations

import csv
import io
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VisualOcrObservation:
    text: str
    mean_confidence: float | None
    engine_version: str
    language: str


def parse_tesseract_tsv(tsv_text: str) -> tuple[str, float | None]:
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    lines: list[str] = []
    current_line: tuple[str, str, str, str] | None = None
    words: list[str] = []
    confidences: list[float] = []

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
    return "\n".join(lines), mean_confidence


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
    text, confidence = parse_tesseract_tsv(result.stdout)
    return VisualOcrObservation(
        text=text,
        mean_confidence=confidence,
        engine_version=tesseract_version(),
        language=language,
    )
