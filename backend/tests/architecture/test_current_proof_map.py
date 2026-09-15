from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
GUARANTEES = REPO_ROOT / "docs" / "testing" / "current-guarantees.toml"
PROOF_MAP = REPO_ROOT / "docs" / "testing" / "current-proof-map.toml"


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_every_current_guarantee_is_mapped_or_explicitly_gapped() -> None:
    guarantees_payload = _load(GUARANTEES)
    proof_payload = _load(PROOF_MAP)

    guarantees = {item["id"] for item in guarantees_payload["guarantees"]}  # type: ignore[index]
    proofs = {item["guarantee"] for item in proof_payload.get("proofs", [])}  # type: ignore[union-attr]
    gaps = {item["guarantee"] for item in proof_payload.get("gaps", [])}  # type: ignore[union-attr]

    unknown = (proofs | gaps) - guarantees
    missing = guarantees - (proofs | gaps)

    assert not unknown, f"Proof map references unknown guarantees: {sorted(unknown)}"
    assert not missing, (
        "Current guarantees must not disappear into undocumented evidence debt. "
        f"Map them to representative proof or record an explicit gap: {sorted(missing)}"
    )


def test_representative_proof_paths_exist_but_are_not_normative() -> None:
    payload = _load(PROOF_MAP)
    assert payload["normative"] is False
    assert payload["guarantees"] == "docs/testing/current-guarantees.toml"

    proofs = payload.get("proofs", [])
    assert proofs
    for proof in proofs:  # type: ignore[assignment]
        path = proof["path"]
        assert (REPO_ROOT / path).is_file(), f"Representative proof path no longer exists: {path}"
        assert proof["evidence"], f"Representative proof has no evidence classification: {path}"


def test_evidence_gaps_are_specific_not_placeholder_debt() -> None:
    payload = _load(PROOF_MAP)
    gaps = payload.get("gaps", [])

    for gap in gaps:  # type: ignore[assignment]
        assert gap["missing_evidence"], f"Gap for {gap['guarantee']} must name missing evidence"
        reason = gap["reason"].strip()
        assert len(reason) >= 40, (
            f"Gap for {gap['guarantee']} needs an actionable explanation, not a TODO placeholder"
        )
        assert "todo" not in reason.lower()
