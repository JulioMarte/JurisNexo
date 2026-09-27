from __future__ import annotations

import pytest

from jurisnexo.normalization.visual_identifier_benchmark import (
    VisualIdentifierCase,
    extract_scj_identifier,
    select_verification_target,
    select_visual_identifier_cases,
    visible_token_is_exact,
)


def _case(index: int) -> VisualIdentifierCase:
    return VisualIdentifierCase(
        object_key=f"{index}.pdf",
        page_index=index,
        expected_identifier=f"SCJ-AA-22-{index:04d}",
        gold_source="test",
    )


def test_extract_identifier_ignores_visible_prefix() -> None:
    assert extract_scj_identifier("NÚM. SCJ-SS-22-0514") == "SCJ-SS-22-0514"
    assert extract_scj_identifier("ÚM. SCJ-SS-22-0514\n") == "SCJ-SS-22-0514"


def test_extract_identifier_rejects_missing_identifier() -> None:
    assert extract_scj_identifier("NÚM. 123") is None


def test_deterministic_selection() -> None:
    cases = [_case(index) for index in range(5)]
    selected = select_visual_identifier_cases(
        cases,
        sample_size=2,
        selection="deterministic",
        seed=7,
    )
    assert selected == cases[:2]


def test_random_selection_is_seeded() -> None:
    cases = [_case(index) for index in range(10)]
    first = select_visual_identifier_cases(
        cases,
        sample_size=4,
        selection="random",
        seed=7,
    )
    second = select_visual_identifier_cases(
        cases,
        sample_size=4,
        selection="random",
        seed=7,
    )
    assert first == second


def test_selection_refuses_oversampling() -> None:
    with pytest.raises(ValueError, match="only 1"):
        select_visual_identifier_cases(
            [_case(1)],
            sample_size=2,
            selection="deterministic",
            seed=7,
        )


def test_select_verification_target_prefers_legal_identifier() -> None:
    assert select_verification_target(
        "Sentencia SCJ-SS-22-0514 del año 2026"
    ) == ("SCJ-SS-22-0514", "SCJ-SS-22-0519")


def test_select_verification_target_falls_back_to_long_number() -> None:
    assert select_verification_target("Expediente número 123456") == (
        "123456",
        "123459",
    )


def test_visible_token_exactness_is_fail_closed() -> None:
    assert visible_token_is_exact(
        expected_visible_token="SCJ-SS-22-0514",
        observed_visible_token="SCJ-SS-22-0514",
    )
    assert not visible_token_is_exact(
        expected_visible_token="SCJ-SS-22-0514",
        observed_visible_token="SCJ-SS-22-0519",
    )
    assert not visible_token_is_exact(
        expected_visible_token="SCJ-SS-22-0514",
        observed_visible_token=None,
    )
