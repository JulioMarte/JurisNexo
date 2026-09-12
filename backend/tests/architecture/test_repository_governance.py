from __future__ import annotations

import os
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def test_normative_architecture_sources_are_discoverable() -> None:
    required = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "19-documentation-crosswalk.md",
        REPO_ROOT / "docs" / "22-architecture-fitness-functions.md",
        REPO_ROOT / "docs" / "testing" / "current-guarantees.toml",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert not missing, f"Missing normative architecture/governance sources: {missing}"


def test_agent_operating_map_routes_to_executable_architecture_policy() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    required_references = {
        "docs/22-architecture-fitness-functions.md",
        "docs/testing/current-guarantees.toml",
        "tests/architecture",
    }
    missing = sorted(reference for reference in required_references if reference not in agents)
    assert not missing, (
        "AGENTS.md no longer routes coding agents to executable architecture policy: "
        f"missing={missing}. Keep AGENTS as the operational map and detailed policy in docs/."
    )


def test_ci_runs_architecture_fitness_functions_in_required_quality_lane() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Architecture fitness functions" in workflow, (
        "CI no longer has an explicit architecture fitness step. Architecture constraints must "
        "remain visible and blocking in the normal backend-quality lane."
    )
    assert "pytest tests/architecture" in workflow, (
        "CI must run pytest tests/architecture explicitly; relying on an incidental all-tests "
        "command makes the architectural gate too easy to remove or skip unnoticed."
    )
