from __future__ import annotations

from types import SimpleNamespace

import pytest

from jurisnexo.normalization.visual_reference_ocr import (
    parse_tesseract_tsv,
    tesseract_version,
)


def test_parse_tesseract_tsv_reconstructs_lines_and_confidence() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95.0\tSENTENCIA\n"
        "5\t1\t1\t1\t1\t2\t10\t0\t10\t10\t93.0\tSCJ-SS-22-0514\n"
        "5\t1\t1\t1\t2\t1\t0\t10\t10\t10\t91.0\tArtículo\n"
        "5\t1\t1\t1\t2\t2\t10\t10\t10\t10\t89.0\t53\n"
    )

    text, confidence = parse_tesseract_tsv(tsv)

    assert text == "SENTENCIA SCJ-SS-22-0514\nArtículo 53"
    assert confidence == 92.0


def test_parse_tesseract_tsv_handles_missing_confidence() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t-1\tTexto\n"
    )

    text, confidence = parse_tesseract_tsv(tsv)

    assert text == "Texto"
    assert confidence is None


def test_tesseract_version_is_cached_per_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout="tesseract 5.5.0\n",
            stderr="",
        )

    tesseract_version.cache_clear()
    monkeypatch.setattr(
        "jurisnexo.normalization.visual_reference_ocr.subprocess.run",
        fake_run,
    )

    assert tesseract_version() == "tesseract 5.5.0"
    assert tesseract_version() == "tesseract 5.5.0"
    assert calls == 1

    tesseract_version.cache_clear()
