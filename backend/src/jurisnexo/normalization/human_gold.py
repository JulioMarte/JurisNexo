from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

GoldSplit = Literal["calibration", "holdout", "adversarial"]
ReviewStatus = Literal["pending", "verified", "rejected"]

_ALLOWED_SPLITS = {"calibration", "holdout", "adversarial"}
_ALLOWED_STATUSES = {"pending", "verified", "rejected"}


@dataclass(frozen=True, slots=True)
class HumanGoldCriticalFact:
    category: str
    value: str
    evidence_excerpt: str


@dataclass(frozen=True, slots=True)
class HumanGoldPage:
    source_sha256: str
    object_key: str
    page_index: int
    split: GoldSplit
    page_roles: tuple[str, ...]
    image_sha256: str
    native_reference_sha256: str | None
    review_status: ReviewStatus
    adjudicated_text: str | None
    reviewer_id: str | None
    reviewed_at: str | None
    critical_facts: tuple[HumanGoldCriticalFact, ...] = ()

    @property
    def is_verified(self) -> bool:
        return self.review_status == "verified"


@dataclass(frozen=True, slots=True)
class HumanGoldSet:
    schema_version: int
    set_id: str
    pages: tuple[HumanGoldPage, ...]

    @property
    def verified_pages(self) -> tuple[HumanGoldPage, ...]:
        return tuple(page for page in self.pages if page.is_verified)


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc


def _parse_reviewed_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")


def validate_human_gold_set(gold: HumanGoldSet) -> None:
    if gold.schema_version != 1:
        raise ValueError("unsupported human-gold schema_version")
    if not gold.set_id.strip():
        raise ValueError("set_id must not be empty")
    if not gold.pages:
        raise ValueError("human gold set must contain at least one page")

    seen_pages: set[tuple[str, int]] = set()
    document_splits: dict[str, str] = {}
    for page in gold.pages:
        _require_sha256(page.source_sha256, field="source_sha256")
        _require_sha256(page.image_sha256, field="image_sha256")
        if page.native_reference_sha256 is not None:
            _require_sha256(
                page.native_reference_sha256,
                field="native_reference_sha256",
            )
        if not page.object_key.strip():
            raise ValueError("object_key must not be empty")
        if page.page_index < 0:
            raise ValueError("page_index must be non-negative")
        if page.split not in _ALLOWED_SPLITS:
            raise ValueError(f"unsupported gold split: {page.split}")
        if page.review_status not in _ALLOWED_STATUSES:
            raise ValueError(
                f"unsupported review_status: {page.review_status}"
            )
        if not page.page_roles or any(
            not role.strip() for role in page.page_roles
        ):
            raise ValueError("page_roles must contain non-empty role names")

        identity = (page.source_sha256, page.page_index)
        if identity in seen_pages:
            raise ValueError(
                "same source page appears more than once in human gold"
            )
        seen_pages.add(identity)

        existing_split = document_splits.setdefault(
            page.source_sha256,
            page.split,
        )
        if existing_split != page.split:
            raise ValueError(
                "one source document cannot cross calibration/holdout/"
                "adversarial splits"
            )

        if page.review_status == "verified":
            if not (page.adjudicated_text or "").strip():
                raise ValueError(
                    "verified gold requires non-empty adjudicated_text"
                )
            if not (page.reviewer_id or "").strip():
                raise ValueError("verified gold requires reviewer_id")
            if not (page.reviewed_at or "").strip():
                raise ValueError("verified gold requires reviewed_at")
            _parse_reviewed_at(page.reviewed_at or "")
        elif page.review_status == "pending":
            if page.reviewer_id is not None or page.reviewed_at is not None:
                raise ValueError(
                    "pending gold cannot claim reviewer identity or review time"
                )

        for fact in page.critical_facts:
            if not fact.category.strip():
                raise ValueError("critical fact category must not be empty")
            if not fact.value.strip():
                raise ValueError("critical fact value must not be empty")
            if not fact.evidence_excerpt.strip():
                raise ValueError(
                    "critical fact evidence_excerpt must not be empty"
                )


def human_gold_summary(gold: HumanGoldSet) -> dict[str, object]:
    counts: dict[str, dict[str, int]] = {
        split: {"pending": 0, "verified": 0, "rejected": 0}
        for split in sorted(_ALLOWED_SPLITS)
    }
    documents: dict[str, set[str]] = {
        split: set() for split in _ALLOWED_SPLITS
    }
    for page in gold.pages:
        counts[page.split][page.review_status] += 1
        documents[page.split].add(page.source_sha256)
    return {
        "schema_version": gold.schema_version,
        "set_id": gold.set_id,
        "page_counts": counts,
        "document_counts": {
            split: len(values)
            for split, values in sorted(documents.items())
        },
        "verified_page_count": len(gold.verified_pages),
    }


def _optional_string(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    return None if value is None else str(value)


def load_human_gold_set(path: Path) -> HumanGoldSet:
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("human gold payload must be an object")
    payload = cast(dict[str, object], decoded)

    raw_pages_value = payload.get("pages")
    if not isinstance(raw_pages_value, list):
        raise ValueError("human gold pages must be an array")
    raw_pages = cast(list[object], raw_pages_value)

    pages: list[HumanGoldPage] = []
    for raw_value in raw_pages:
        if not isinstance(raw_value, dict):
            raise ValueError("every human gold page must be an object")
        raw = cast(dict[str, object], raw_value)

        raw_facts_value = raw.get("critical_facts", [])
        if not isinstance(raw_facts_value, list):
            raise ValueError("critical_facts must be an array")
        raw_facts = cast(list[object], raw_facts_value)
        facts: list[HumanGoldCriticalFact] = []
        for fact_value in raw_facts:
            if not isinstance(fact_value, dict):
                raise ValueError("every critical fact must be an object")
            fact = cast(dict[str, object], fact_value)
            facts.append(
                HumanGoldCriticalFact(
                    category=str(fact["category"]),
                    value=str(fact["value"]),
                    evidence_excerpt=str(fact["evidence_excerpt"]),
                )
            )

        raw_roles_value = raw.get("page_roles")
        if not isinstance(raw_roles_value, list):
            raise ValueError("page_roles must be an array")
        raw_roles = cast(list[object], raw_roles_value)
        pages.append(
            HumanGoldPage(
                source_sha256=str(raw["source_sha256"]),
                object_key=str(raw["object_key"]),
                page_index=int(str(raw["page_index"])),
                split=cast(GoldSplit, str(raw["split"])),
                page_roles=tuple(str(role) for role in raw_roles),
                image_sha256=str(raw["image_sha256"]),
                native_reference_sha256=_optional_string(
                    raw, "native_reference_sha256"
                ),
                review_status=cast(
                    ReviewStatus, str(raw["review_status"])
                ),
                adjudicated_text=_optional_string(raw, "adjudicated_text"),
                reviewer_id=_optional_string(raw, "reviewer_id"),
                reviewed_at=_optional_string(raw, "reviewed_at"),
                critical_facts=tuple(facts),
            )
        )

    gold = HumanGoldSet(
        schema_version=int(str(payload.get("schema_version", 0))),
        set_id=str(payload.get("set_id", "")),
        pages=tuple(pages),
    )
    validate_human_gold_set(gold)
    return gold
