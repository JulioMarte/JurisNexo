from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TypedDict, cast

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
GUARANTEES = REPO_ROOT / "docs" / "testing" / "current-guarantees.toml"
PROOF_MAP = REPO_ROOT / "docs" / "testing" / "current-proof-map.toml"


class Guarantee(TypedDict):
    id: str


class Proof(TypedDict):
    guarantee: str
    path: str
    evidence: list[str]


class Gap(TypedDict):
    guarantee: str
    missing_evidence: list[str]
    reason: str


def _guarantees() -> list[Guarantee]:
    with GUARANTEES.open("rb") as handle:
        payload = tomllib.load(handle)
    return cast(list[Guarantee], payload["guarantees"])


def _proof_map() -> tuple[dict[str, object], list[Proof], list[Gap]]:
    with PROOF_MAP.open("rb") as handle:
        payload = tomllib.load(handle)
    return (
        payload,
        cast(list[Proof], payload.get("proofs", [])),
        cast(list[Gap], payload.get("gaps", [])),
    )


def test_every_current_guarantee_is_mapped_or_explicitly_gapped() -> None:
    _, proofs, gaps = _proof_map()
    guarantees = {item["id"] for item in _guarantees()}
    proof_ids = {item["guarantee"] for item in proofs}
    gap_ids = {item["guarantee"] for item in gaps}

    unknown = (proof_ids | gap_ids) - guarantees
    missing = guarantees - (proof_ids | gap_ids)

    assert not unknown, f"Proof map references unknown guarantees: {sorted(unknown)}"
    assert not missing, (
        "Current guarantees must not disappear into undocumented evidence debt. "
        f"Map them to representative proof or record an explicit gap: {sorted(missing)}"
    )


def test_representative_proof_paths_exist_but_are_not_normative() -> None:
    payload, proofs, _ = _proof_map()
    assert payload["normative"] is False
    assert payload["guarantees"] == "docs/testing/current-guarantees.toml"
    assert proofs

    for proof in proofs:
        path = proof["path"]
        assert (REPO_ROOT / path).is_file(), f"Representative proof path no longer exists: {path}"
        assert proof["evidence"], f"Representative proof has no evidence classification: {path}"


def test_evidence_gaps_are_specific_not_placeholder_debt() -> None:
    _, _, gaps = _proof_map()

    for gap in gaps:
        assert gap["missing_evidence"], f"Gap for {gap['guarantee']} must name missing evidence"
        reason = gap["reason"].strip()
        assert len(reason) >= 40, (
            f"Gap for {gap['guarantee']} needs an actionable explanation, not a TODO placeholder"
        )
        assert "todo" not in reason.lower()
