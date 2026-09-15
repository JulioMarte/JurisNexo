from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_test_authoring_policy_is_discoverable_and_routed() -> None:
    required = [
        "docs/testing/README.md",
        "docs/testing/repository-governance-contract.md",
        "docs/testing/evidence-authoring-guide.md",
        "docs/testing/current-guarantees.toml",
        "backend/tests/AGENTS.md",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert not missing, f"Missing canonical test-governance sources: {missing}"

    root_agents = _read("AGENTS.md")
    test_agents = _read("backend/tests/AGENTS.md")

    for reference in (
        "docs/testing/repository-governance-contract.md",
        "docs/testing/evidence-authoring-guide.md",
        "docs/testing/current-guarantees.toml",
    ):
        assert reference in root_agents, (
            "Repository AGENTS.md must route agents to canonical test governance: "
            f"missing {reference}"
        )

    for reference in (
        "docs/testing/README.md",
        "docs/testing/repository-governance-contract.md",
        "docs/testing/evidence-authoring-guide.md",
        "docs/testing/current-guarantees.toml",
    ):
        assert reference in test_agents, (
            "backend/tests/AGENTS.md must route test authors to canonical evidence policy: "
            f"missing {reference}"
        )


def test_editor_and_model_instruction_files_are_adapters_not_parallel_manuals() -> None:
    adapters = {
        "CLAUDE.md": _read("CLAUDE.md"),
        "GEMINI.md": _read("GEMINI.md"),
        ".github/copilot-instructions.md": _read(".github/copilot-instructions.md"),
    }

    for path, content in adapters.items():
        assert "AGENTS.md" in content, f"{path} must route back to canonical AGENTS.md"
        assert "docs/" in content, f"{path} must route durable policy to docs/"
        assert "adapter" in content.lower(), (
            f"{path} must identify itself as an adapter, not a competing architecture manual"
        )

    copilot = adapters[".github/copilot-instructions.md"]
    assert "backend/tests/AGENTS.md" in copilot
    assert "docs/testing/evidence-authoring-guide.md" in copilot


def test_guarantee_inventory_tracks_current_test_and_branch_governance() -> None:
    with (REPO_ROOT / "docs/testing/current-guarantees.toml").open("rb") as handle:
        inventory = tomllib.load(handle)

    guarantees = {item["id"]: item for item in inventory["guarantees"]}

    assert "FIT-TEST-EVIDENCE-001" in guarantees, (
        "The normative inventory must explicitly protect falsifiable test-evidence discipline."
    )
    assert "FIT-BRANCH-WORKFLOW-001" in guarantees

    branch_statement = guarantees["FIT-BRANCH-WORKFLOW-001"]["statement"]
    assert "development is the canonical integration branch" in branch_statement
    assert "main is release-only" in branch_statement

    evidence_statement = guarantees["FIT-TEST-EVIDENCE-001"]["statement"]
    assert "falsifiable evidence" in evidence_statement
    assert "incidental test filenames" in evidence_statement


def test_test_policy_requires_plausible_defect_and_independent_oracle() -> None:
    guide = _read("docs/testing/evidence-authoring-guide.md")
    test_agents = _read("backend/tests/AGENTS.md")

    for phrase in (
        "plausible defect",
        "independent oracle",
        "authoritative outcome",
        "Never weaken a test solely because the implementation currently fails it",
    ):
        combined = f"{guide}\n{test_agents}"
        assert phrase.lower() in combined.lower(), (
            "Test governance lost an evidence-integrity requirement: " f"missing {phrase!r}"
        )
