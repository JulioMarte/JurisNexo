from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
SCRIPT = REPO_ROOT / "backend/scripts/ci/build_engineering_quality_report.py"
PACKAGE_ROOT = REPO_ROOT / "backend/src/jurisnexo"
WORKFLOW = REPO_ROOT / ".github/workflows/engineering-quality.yml"
POLICY = REPO_ROOT / "docs/24-engineering-quality-signals.md"


def _build_report(tmp_path: Path) -> dict[str, object]:
    output = tmp_path / "engineering-quality.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def test_engineering_quality_report_matches_current_component_graph(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    assert report["schema_version"] == "jurisnexo-engineering-quality/v1"
    assert report["authority"] == "maintainability-signals-are-non-blocking"

    coupling = report["component_coupling"]
    assert isinstance(coupling, dict)
    components = coupling["components"]
    edges = coupling["edges"]
    assert isinstance(components, list)
    assert isinstance(edges, list)

    expected_components = {
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__") and any(path.rglob("*.py"))
    }
    actual_components = {str(item["component"]) for item in components}
    assert actual_components == expected_components

    edge_pairs = {(str(edge["source"]), str(edge["target"])) for edge in edges}
    assert all(source != target for source, target in edge_pairs)
    assert all(
        source in actual_components and target in actual_components
        for source, target in edge_pairs
    )

    for item in components:
        component = str(item["component"])
        inbound = sorted(source for source, target in edge_pairs if target == component)
        outbound = sorted(target for source, target in edge_pairs if source == component)
        assert item["inbound_components"] == inbound
        assert item["outbound_components"] == outbound
        assert item["fan_in"] == len(inbound)
        assert item["fan_out"] == len(outbound)


def test_file_size_signals_are_complete_and_non_blocking(tmp_path: Path) -> None:
    report = _build_report(tmp_path)
    policy = report["policy"]
    assert isinstance(policy, dict)
    assert policy["file_loc_threshold_status"] == "review-signal-not-architecture-cliff"
    assert "no numeric fan-in/fan-out cliff" in str(policy["coupling_policy"])

    measurements = report["file_measurements"]
    candidates = report["review_candidates"]
    assert isinstance(measurements, list)
    assert isinstance(candidates, list)

    threshold = int(policy["file_loc_review_threshold"])
    expected_candidates = {
        str(item["path"])
        for item in measurements
        if int(item["effective_loc"]) > threshold
    }
    actual_candidates = {str(item["path"]) for item in candidates}
    assert actual_candidates == expected_candidates
    assert all((REPO_ROOT / str(item["path"])).is_file() for item in measurements)
    assert all(int(item["effective_loc"]) >= 0 for item in measurements)


def test_engineering_quality_signals_are_visible_but_not_a_numeric_merge_gate() -> None:
    assert SCRIPT.is_file()
    assert POLICY.is_file()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")

    assert "build_engineering_quality_report.py" in workflow
    assert "engineering-quality.json" in workflow
    assert "actions/upload-artifact" in workflow
    assert "review-signal-not-architecture-cliff" in (
        REPO_ROOT / "backend/scripts/ci/build_engineering_quality_report.py"
    ).read_text(encoding="utf-8")
    assert "not a blocking architecture limit" in policy
    assert "There is intentionally no synthetic architecture score" in policy
