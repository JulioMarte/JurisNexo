from __future__ import annotations

import json
from pathlib import Path

import pytest

from jurisnexo.normalization.visual_page_benchmark import (
    VisualPageCase,
    load_visual_page_manifest,
    select_visual_page_cases,
)


def _case(index: int) -> VisualPageCase:
    return VisualPageCase(
        object_key=f"{index}.pdf",
        page_index=index,
        gold_source="test",
    )


def test_deterministic_selection_is_stable() -> None:
    cases = [_case(index) for index in range(5)]
    selected = select_visual_page_cases(
        cases,
        sample_size=3,
        selection="deterministic",
        seed=7,
    )
    assert selected == cases[:3]


def test_random_selection_is_reproducible() -> None:
    cases = [_case(index) for index in range(10)]
    first = select_visual_page_cases(
        cases,
        sample_size=4,
        selection="random",
        seed=7,
    )
    second = select_visual_page_cases(
        cases,
        sample_size=4,
        selection="random",
        seed=7,
    )
    assert first == second


def test_selection_rejects_oversampling() -> None:
    with pytest.raises(ValueError, match="only 1"):
        select_visual_page_cases(
            [_case(1)],
            sample_size=2,
            selection="deterministic",
            seed=7,
        )


def test_curated_manifest_loads_page_cases(tmp_path: Path) -> None:
    manifest = tmp_path / "cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "object_key": "a.pdf",
                        "page_index": 4,
                        "gold_source": "human_curated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_visual_page_manifest(manifest) == [
        VisualPageCase(
            object_key="a.pdf",
            page_index=4,
            gold_source="human_curated",
        )
    ]
