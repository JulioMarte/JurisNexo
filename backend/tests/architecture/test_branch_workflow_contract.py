from __future__ import annotations

import os
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def test_main_is_documented_as_canonical_integration_branch() -> None:
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "`main` is the canonical integration and deployable branch" in contributing
    assert "short-lived branch" in contributing
    assert "CI aggregate" in contributing


def test_ci_keeps_pull_requests_and_main_as_normal_integration_surface() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "name: CI aggregate" in workflow
    assert "Require all jobs to pass" in workflow


def test_branch_cleanup_only_deletes_successfully_merged_same_repo_heads() -> None:
    cleanup = (REPO_ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(
        encoding="utf-8"
    )

    required_guards = {
        "github.event.pull_request.merged == true",
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.event.pull_request.head.ref != github.event.repository.default_branch",
    }
    missing = sorted(guard for guard in required_guards if guard not in cleanup)

    assert not missing, (
        "Merged-branch cleanup lost a required safety guard: "
        f"missing={missing}. Cleanup must never delete an unmerged, fork-owned, or default branch."
    )
    assert "--method DELETE" in cleanup
