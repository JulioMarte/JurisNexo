#!/usr/bin/env python3
"""Inventory JurisNexo tests by physical scope and effective evidence metadata."""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from collections import Counter
from pathlib import Path

EVIDENCE_MARKERS = frozenset(
    {
        "fitness",
        "contract",
        "invariant",
        "adversarial",
        "benchmark",
        "security",
        "provenance",
        "temporal",
        "retrieval",
        "concurrency",
        "historical",
    }
)

# These names strongly suggest checkpoint/release evidence rather than current
# deterministic repository architecture. They are deliberately conservative:
# ambiguous names should be reviewed by a human rather than rejected by pattern.
HISTORICAL_ARCHITECTURE_HINTS = (
    "candidate_freeze",
    "release_inventory",
    "release_manifest",
    "historical_release",
    "frozen_baseline",
)


def _configured_markers(pyproject: Path) -> set[str]:
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    entries = payload["tool"]["pytest"]["ini_options"]["markers"]
    return {str(entry).split(":", 1)[0].strip() for entry in entries}


def _explicit_pytest_markers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    markers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if not isinstance(value, ast.Attribute) or value.attr != "mark":
            continue
        if isinstance(value.value, ast.Name) and value.value.id == "pytest":
            markers.add(node.attr)
    return markers


def _scope(path: Path, test_root: Path) -> str:
    relative = path.relative_to(test_root)
    return relative.parts[0] if len(relative.parts) > 1 else "root"


def _effective_evidence_markers(scope: str, explicit: set[str]) -> set[str]:
    effective = set(explicit & EVIDENCE_MARKERS)
    if scope == "architecture":
        effective.add("fitness")
    elif scope == "historical":
        effective.add("historical")
    return effective


def build_inventory(repo_root: Path) -> tuple[dict[str, object], list[str]]:
    backend_root = repo_root / "backend"
    test_root = backend_root / "tests"
    pyproject = backend_root / "pyproject.toml"

    configured = _configured_markers(pyproject)
    missing_markers = sorted(EVIDENCE_MARKERS - configured)

    tests: list[dict[str, object]] = []
    scope_counts: Counter[str] = Counter()
    marker_counts: Counter[str] = Counter()
    historical_contamination: list[str] = []
    unclassified_current: list[str] = []

    for path in sorted(test_root.rglob("test_*.py")):
        relative = path.relative_to(repo_root).as_posix()
        scope = _scope(path, test_root)
        explicit = _explicit_pytest_markers(path)
        explicit_evidence = explicit & EVIDENCE_MARKERS
        effective_evidence = _effective_evidence_markers(scope, explicit)

        scope_counts[scope] += 1
        marker_counts.update(effective_evidence)
        tests.append(
            {
                "path": relative,
                "scope": scope,
                "explicit_evidence_markers": sorted(explicit_evidence),
                "effective_evidence_markers": sorted(effective_evidence),
            }
        )

        if scope == "architecture" and (
            "historical" in explicit
            or "benchmark" in explicit
            or any(hint in path.stem for hint in HISTORICAL_ARCHITECTURE_HINTS)
        ):
            historical_contamination.append(relative)
        if scope not in {"architecture", "historical"} and not effective_evidence:
            unclassified_current.append(relative)

    failures: list[str] = []
    if missing_markers:
        failures.append(f"missing pytest evidence markers: {missing_markers}")
    if historical_contamination:
        failures.append(
            "historical/release evidence is mixed into tests/architecture: "
            + ", ".join(historical_contamination)
        )

    payload: dict[str, object] = {
        "schema_version": 1,
        "test_file_count": len(tests),
        "physical_scope_counts": dict(sorted(scope_counts.items())),
        "effective_evidence_marker_counts": dict(sorted(marker_counts.items())),
        "historical_architecture_contamination": historical_contamination,
        # This is review debt, not a hard failure. A small unit test can be useful
        # without pretending to prove a durable semantic guarantee.
        "unclassified_current_test_files": unclassified_current,
        "tests": tests,
    }
    return payload, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    payload, failures = build_inventory(repo_root)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"test files: {payload['test_file_count']}")
    print(f"physical scopes: {payload['physical_scope_counts']}")
    print(f"evidence markers: {payload['effective_evidence_marker_counts']}")
    print(
        "unclassified current test files: "
        f"{len(payload['unclassified_current_test_files'])}"
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("test architecture inventory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
