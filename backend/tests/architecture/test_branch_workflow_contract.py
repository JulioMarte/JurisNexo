from __future__ import annotations

import os
from pathlib import Path

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _validate_pull_request_topology(*, base_ref: str, head_ref: str) -> None:
    if not base_ref:
        return

    if base_ref == "main":
        assert head_ref == "development", (
            "Invalid release topology: pull requests to 'main' must come from 'development'. "
            f"Observed '{head_ref or '<unknown>'} -> main'. Ordinary work must integrate through "
            "development first."
        )
        return

    assert base_ref == "development", (
        "Invalid pull-request topology: ordinary JurisNexo PRs must target 'development'. "
        f"Observed '{head_ref or '<unknown>'} -> {base_ref}'."
    )
    assert head_ref and head_ref not in {"main", "development"}, (
        "Invalid ordinary PR head: work targeting 'development' must use a dedicated short-lived "
        "branch rather than a long-lived integration/release branch."
    )


def test_pull_request_targets_canonical_integration_branch() -> None:
    _validate_pull_request_topology(
        base_ref=os.environ.get("GITHUB_BASE_REF", ""),
        head_ref=os.environ.get("GITHUB_HEAD_REF", ""),
    )


def test_ordinary_pr_must_target_development() -> None:
    with pytest.raises(AssertionError, match="must target 'development'"):
        _validate_pull_request_topology(
            base_ref="release-candidate",
            head_ref="feature/example",
        )


def test_only_development_can_promote_to_main() -> None:
    with pytest.raises(AssertionError, match="must come from 'development'"):
        _validate_pull_request_topology(base_ref="main", head_ref="feature/bypass")


def test_development_to_main_is_valid_release_topology() -> None:
    _validate_pull_request_topology(base_ref="main", head_ref="development")


def test_long_lived_branches_cannot_be_ordinary_pr_heads() -> None:
    with pytest.raises(AssertionError, match="dedicated short-lived branch"):
        _validate_pull_request_topology(base_ref="development", head_ref="main")


def test_development_is_documented_as_canonical_integration_branch() -> None:
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "`development` is the canonical integration branch" in contributing
    assert "`main` is the validated release branch" in contributing
    assert "CI aggregate" in contributing


def test_ci_covers_pull_requests_and_both_long_lived_branches() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "- main" in workflow
    assert "- development" in workflow
    assert "name: CI aggregate" in workflow
    assert "Require all jobs to pass" in workflow


def test_branch_cleanup_protects_long_lived_branches() -> None:
    cleanup = (REPO_ROOT / ".github" / "workflows" / "branch-hygiene.yml").read_text(
        encoding="utf-8"
    )

    required_guards = {
        "github.event.pull_request.merged == true",
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.event.pull_request.head.ref != 'main'",
        "github.event.pull_request.head.ref != 'development'",
    }
    missing = sorted(guard for guard in required_guards if guard not in cleanup)

    assert not missing, (
        "Merged-branch cleanup lost a required safety guard: "
        f"missing={missing}. Cleanup must never delete an unmerged, fork-owned, main, or "
        "development branch."
    )
    assert "--method DELETE" in cleanup


def test_integration_lane_matches_pr_head_when_present() -> None:
    head_ref = os.environ.get("GITHUB_HEAD_REF", "")
    if not head_ref or head_ref == "development":
        return

    lane = (REPO_ROOT / ".github" / "development-integration-lane").read_text(
        encoding="utf-8"
    ).strip()
    assert lane == head_ref, (
        "The development integration lane must identify the current ordinary PR head exactly. "
        f"Expected '{head_ref}', found '{lane}'."
    )
