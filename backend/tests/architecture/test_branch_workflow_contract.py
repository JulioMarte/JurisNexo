from __future__ import annotations

import os
from pathlib import Path

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _validate_pull_request_topology(*, base_ref: str, head_ref: str) -> None:
    if not base_ref:
        return

    assert base_ref == "main", (
        "Invalid pull-request topology: ordinary JurisNexo PRs must target 'main', "
        f"the canonical integration branch. Observed '{head_ref or '<unknown>'} -> {base_ref}'. "
        "Do not introduce a permanent dev/development integration branch unless the documented "
        "deployment lifecycle is explicitly changed first."
    )
    assert head_ref and head_ref != "main", (
        "Invalid pull-request head: normal work must use a dedicated short-lived branch rather "
        "than opening a PR from 'main' to itself."
    )


def test_pull_request_targets_canonical_integration_branch() -> None:
    _validate_pull_request_topology(
        base_ref=os.environ.get("GITHUB_BASE_REF", ""),
        head_ref=os.environ.get("GITHUB_HEAD_REF", ""),
    )


def test_non_main_pr_target_receives_actionable_error() -> None:
    with pytest.raises(AssertionError, match="must target 'main'"):
        _validate_pull_request_topology(
            base_ref="development",
            head_ref="feature/parallel-integration-branch",
        )


def test_main_cannot_be_used_as_ordinary_pr_head() -> None:
    with pytest.raises(AssertionError, match="dedicated short-lived branch"):
        _validate_pull_request_topology(base_ref="main", head_ref="main")


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
