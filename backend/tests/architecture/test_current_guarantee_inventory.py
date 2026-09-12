from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypedDict, cast

REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY = REPO_ROOT / "docs" / "testing" / "current-guarantees.toml"

KNOWN_CLASSIFICATIONS = {"HARD", "CONTROLLED", "FLEXIBLE", "HISTORICAL"}
KNOWN_EVIDENCE = {
    "invariant",
    "contract",
    "fitness",
    "adversarial",
    "benchmark",
    "integration",
    "security",
}
KNOWN_RISKS = {
    "security",
    "provenance",
    "legal_quality",
    "architecture",
    "operations",
}


class Guarantee(TypedDict):
    id: str
    statement: str
    severity: str
    classification: str
    required_evidence: list[str]
    risk: list[str]


def _guarantees() -> list[Guarantee]:
    payload = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
    return cast(list[Guarantee], payload["guarantees"])


def test_current_guarantee_inventory_has_unique_semantic_ids() -> None:
    guarantees = _guarantees()
    identifiers = [item["id"] for item in guarantees]

    assert guarantees, "The normative guarantee inventory must not be empty."
    assert len(identifiers) == len(set(identifiers)), "Guarantee IDs must be unique."
    assert all(item["statement"].strip() for item in guarantees)


def test_current_guarantee_inventory_uses_declared_vocabularies() -> None:
    for guarantee in _guarantees():
        assert guarantee["severity"] in {"critical", "high", "medium"}
        assert guarantee["classification"] in KNOWN_CLASSIFICATIONS
        assert guarantee["required_evidence"]
        assert set(guarantee["required_evidence"]) <= KNOWN_EVIDENCE
        assert set(guarantee["risk"]) <= KNOWN_RISKS


def test_hard_critical_non_fitness_guarantees_require_behavioral_proof() -> None:
    behavioral_evidence = {"invariant", "adversarial", "benchmark", "integration", "security"}
    for guarantee in _guarantees():
        if guarantee["classification"] != "HARD" or guarantee["severity"] != "critical":
            continue
        if "fitness" in guarantee["required_evidence"]:
            continue
        assert set(guarantee["required_evidence"]) & behavioral_evidence, (
            f"{guarantee['id']} is HARD/critical but has no behavioral evidence class. "
            "Add invariant, adversarial, benchmark, integration, or security proof as appropriate."
        )


def test_current_guarantee_inventory_does_not_freeze_test_file_shape() -> None:
    source = INVENTORY.read_text(encoding="utf-8")

    assert "backend/tests/" not in source
    assert "tests/architecture/" not in source
    for guarantee in _guarantees():
        assert "test" not in guarantee
        assert "path" not in guarantee
        assert "file" not in guarantee
