from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
REPORT_SCRIPT = REPO_ROOT / "backend/scripts/ci/build_engineering_quality_report.py"
DIFF_SCRIPT = REPO_ROOT / "backend/scripts/ci/build_architecture_diff.py"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def _commit(repo: Path, message: str) -> None:
    add = _run("git", "add", ".", cwd=repo)
    assert add.returncode == 0, add.stderr
    commit = _run("git", "commit", "-m", message, cwd=repo)
    assert commit.returncode == 0, commit.stderr


def _synthetic_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "backend/src/jurisnexo/a").mkdir(parents=True)
    (repo / "backend/src/jurisnexo/b").mkdir(parents=True)
    (repo / "backend/src/jurisnexo/a/base.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "backend/src/jurisnexo/b/target.py").write_text(
        "def target(value: int) -> int:\n    return value\n",
        encoding="utf-8",
    )
    init = _run("git", "init", cwd=repo)
    assert init.returncode == 0, init.stderr
    assert _run("git", "config", "user.email", "quality@example.invalid", cwd=repo).returncode == 0
    assert _run("git", "config", "user.name", "Quality Fixture", cwd=repo).returncode == 0
    _commit(repo, "base")

    complex_source = """from jurisnexo.b.target import target  # noqa: F401


def decide(value: int) -> int:
    result = value
    if value > 0:
        result += 1
    if value > 1:
        result += 1
    if value > 2:
        result += 1
    if value > 3:
        result += 1
    if value > 4:
        result += 1
    if value > 5:
        result += 1
    if value > 6:
        result += 1
    if value > 7:
        result += 1
    if value > 8:
        result += 1
    if value > 9:
        result += 1
    if value > 10:
        result += 1
    return result
"""
    (repo / "backend/src/jurisnexo/a/complex.py").write_text(complex_source, encoding="utf-8")
    forwarder_source = (
        "from jurisnexo.b.target import target\n\n\n"
        "def forward(value: int) -> int:\n"
        "    return target(value)\n"
    )
    (repo / "backend/src/jurisnexo/a/forwarder.py").write_text(
        forwarder_source,
        encoding="utf-8",
    )
    _commit(repo, "head")
    return repo


def test_architecture_diff_reports_edges_file_growth_suppressions_and_navigation(
    tmp_path: Path,
) -> None:
    repo = _synthetic_repo(tmp_path)
    output = repo / ".ci/architecture-diff.json"
    result = _run(
        sys.executable,
        str(DIFF_SCRIPT),
        "--repo-root",
        str(repo),
        "--base-ref",
        "HEAD^",
        "--output",
        str(output),
        cwd=repo,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "jurisnexo-architecture-diff/v1"
    added_edges = payload["component_coupling"]["added_edges"]
    assert {(item["source"], item["target"]) for item in added_edges} == {("a", "b")}

    deltas = {item["component"]: item for item in payload["component_deltas"]}
    assert deltas["a"]["fan_out"]["delta"] == 1
    assert deltas["b"]["fan_in"]["delta"] == 1
    assert deltas["a"]["effective_loc"]["delta"] > 0

    file_deltas = {item["path"]: item for item in payload["file_deltas"]}
    assert file_deltas["backend/src/jurisnexo/a/complex.py"]["status"] == "added"
    assert file_deltas["backend/src/jurisnexo/a/complex.py"]["effective_loc"]["after"] > 0
    assert payload["suppressions"]["delta"] == 1

    navigation = {item["path"]: item for item in payload["navigation"]}
    forwarder = navigation["backend/src/jurisnexo/a/forwarder.py"]
    assert forwarder["forwarding_only_functions"]["after"] is True


def test_quality_report_turns_complexity_coupling_navigation_and_suppression_into_review_candidates(
    tmp_path: Path,
) -> None:
    repo = _synthetic_repo(tmp_path)
    output = repo / ".ci/engineering-quality.json"
    result = _run(
        sys.executable,
        str(REPORT_SCRIPT),
        "--repo-root",
        str(repo),
        "--base-ref",
        "HEAD^",
        "--output",
        str(output),
        cwd=repo,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))

    triggers = {item["trigger_id"] for item in payload["review_candidates"]}
    assert "QR-CPLX-001" in triggers
    assert "QR-COUPLING-001" in triggers
    assert "QR-NAV-001" in triggers
    assert "QR-SUPPRESS-001" in triggers
    assert all(
        item["classification"] == "REVIEW_CANDIDATE"
        for item in payload["review_candidates"]
    )
    assert (
        payload["policy"]["threshold_status"]
        == "calibration-triggers-not-architecture-cliffs"
    )
