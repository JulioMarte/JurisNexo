from __future__ import annotations

import pytest

from jurisnexo.normalization.human_gold import (
    HumanGoldPage,
    HumanGoldSet,
    human_gold_summary,
    validate_human_gold_set,
)


def _page(
    *,
    source: str,
    page_index: int,
    split: str,
    status: str = "verified",
) -> HumanGoldPage:
    return HumanGoldPage(
        source_sha256=source,
        object_key=f"official/{source}.pdf",
        page_index=page_index,
        split=split,  # type: ignore[arg-type]
        page_roles=("reasoning",),
        image_sha256=("a" * 63) + str(page_index % 10),
        native_reference_sha256="b" * 64,
        review_status=status,  # type: ignore[arg-type]
        adjudicated_text=(
            "SENTENCIA SCJ-SS-22-1191 Articulo 5."
            if status == "verified"
            else None
        ),
        reviewer_id="reviewer-1" if status == "verified" else None,
        reviewed_at="2026-09-24T22:00:00-04:00" if status == "verified" else None,
    )


def test_verified_gold_requires_human_review_metadata() -> None:
    page = _page(
        source="1" * 64,
        page_index=0,
        split="calibration",
    )
    invalid = HumanGoldPage(
        source_sha256=page.source_sha256,
        object_key=page.object_key,
        page_index=page.page_index,
        split=page.split,
        page_roles=page.page_roles,
        image_sha256=page.image_sha256,
        native_reference_sha256=page.native_reference_sha256,
        review_status="verified",
        adjudicated_text=page.adjudicated_text,
        reviewer_id=None,
        reviewed_at=None,
    )
    with pytest.raises(ValueError, match="reviewer_id"):
        validate_human_gold_set(
            HumanGoldSet(
                schema_version=1,
                set_id="fixture",
                pages=(invalid,),
            )
        )


def test_pending_candidate_cannot_claim_human_review_metadata() -> None:
    page = _page(
        source="2" * 64,
        page_index=0,
        split="calibration",
        status="pending",
    )
    invalid = HumanGoldPage(
        source_sha256=page.source_sha256,
        object_key=page.object_key,
        page_index=page.page_index,
        split=page.split,
        page_roles=page.page_roles,
        image_sha256=page.image_sha256,
        native_reference_sha256=page.native_reference_sha256,
        review_status="pending",
        adjudicated_text=None,
        reviewer_id="reviewer-1",
        reviewed_at="2026-09-24T22:00:00-04:00",
    )
    with pytest.raises(ValueError, match="pending gold"):
        validate_human_gold_set(
            HumanGoldSet(
                schema_version=1,
                set_id="fixture",
                pages=(invalid,),
            )
        )


def test_same_document_cannot_cross_calibration_and_holdout() -> None:
    source = "3" * 64
    gold = HumanGoldSet(
        schema_version=1,
        set_id="fixture",
        pages=(
            _page(
                source=source,
                page_index=0,
                split="calibration",
            ),
            _page(
                source=source,
                page_index=1,
                split="holdout",
            ),
        ),
    )
    with pytest.raises(ValueError, match="cannot cross"):
        validate_human_gold_set(gold)


def test_duplicate_source_page_is_rejected() -> None:
    page = _page(
        source="4" * 64,
        page_index=0,
        split="adversarial",
    )
    with pytest.raises(ValueError, match="more than once"):
        validate_human_gold_set(
            HumanGoldSet(
                schema_version=1,
                set_id="fixture",
                pages=(page, page),
            )
        )


def test_summary_never_counts_pending_as_verified() -> None:
    gold = HumanGoldSet(
        schema_version=1,
        set_id="fixture",
        pages=(
            _page(
                source="5" * 64,
                page_index=0,
                split="calibration",
            ),
            _page(
                source="6" * 64,
                page_index=0,
                split="holdout",
                status="pending",
            ),
        ),
    )
    validate_human_gold_set(gold)
    summary = human_gold_summary(gold)
    assert summary["verified_page_count"] == 1
    page_counts = summary["page_counts"]
    assert isinstance(page_counts, dict)
    assert page_counts["holdout"]["pending"] == 1
    assert page_counts["holdout"]["verified"] == 0
