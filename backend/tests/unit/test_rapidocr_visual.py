from __future__ import annotations

import pytest

from jurisnexo.normalization.rapidocr_visual import (
    parallel_text_and_scores,
    parse_rapidocr_output,
)

pytestmark = [pytest.mark.unit]


def test_parse_rapidocr_output_builds_observation_and_confidence_stats() -> None:
    observation = parse_rapidocr_output(
        ["hola", "mundo"],
        [0.9, 0.4],
        low_confidence_threshold=0.5,
        engine_version="3.9.2",
        language="es",
    )

    assert observation.text == "hola\nmundo"
    assert observation.word_count == 2
    assert observation.mean_confidence == pytest.approx(0.65)
    assert observation.median_confidence == pytest.approx(0.65)
    assert observation.p10_confidence == pytest.approx(0.45)
    assert observation.low_confidence_word_ratio == pytest.approx(0.5)
    assert observation.engine_version == "3.9.2"


def test_parse_rapidocr_output_skips_blank_text_and_invalid_scores() -> None:
    observation = parse_rapidocr_output(["hola", "  ", "mundo"], [0.8, "x", 0.6])

    assert observation.text == "hola\nmundo"
    assert observation.word_count == 2
    assert observation.mean_confidence == pytest.approx(0.7)


def test_parse_rapidocr_output_handles_empty_result() -> None:
    observation = parse_rapidocr_output([], [])

    assert observation.text == ""
    assert observation.word_count == 0
    assert observation.mean_confidence is None
    assert observation.median_confidence is None
    assert observation.p10_confidence is None
    assert observation.low_confidence_word_ratio is None


def test_parallel_text_and_scores_reads_object_attributes() -> None:
    class Result:
        txts = ("uno", "dos")
        scores = (0.7, 0.5)

    texts, scores = parallel_text_and_scores(Result())

    assert texts == ["uno", "dos"]
    assert scores == [0.7, 0.5]


def test_parallel_text_and_scores_reads_legacy_rows() -> None:
    legacy = [["box", "uno", 0.7], ["box2", "dos", 0.5]]

    texts, scores = parallel_text_and_scores(legacy)

    assert texts == ["uno", "dos"]
    assert scores == [0.7, 0.5]
