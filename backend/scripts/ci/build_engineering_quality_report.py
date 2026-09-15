from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_architecture_diff import build_architecture_diff  # noqa: E402
from quality_metrics import (  # noqa: E402
    component_dependency_snapshot,
    effective_code_lines,
    file_measurements,
    navigation_observation,
    python_files,
)

SCHEMA_VERSION = "jurisnexo-engineering-quality/v2"
FILE_LOC_REVIEW_THRESHOLD = 120
MCCABE_REVIEW_THRESHOLD = 10
DEFAULT_OUTPUT = Path(".ci/engineering-quality.json")
_C901_SCORE = re.compile(r"\((?P<score>\d+)\s*>\s*(?P<threshold>\d+)\)")
_C901_SUBJECT = re.compile(r"`(?P<subject>[^`]+)`")


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(f"git {' '.join(args)}: {detail}")
    return result


def _changed_python_paths(repo_root: Path, base_ref: str | None) -> list[Path]:
    if not base_ref:
        return [path.relative_to(repo_root) for path in python_files(repo_root)]
    result = _git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base_ref}...HEAD",
        "--",
        "backend/src",
        "backend/tests",
        "backend/migrations",
        "backend/scripts",
    )
    return sorted(
        Path(path)
        for path in result.stdout.splitlines()
        if path.endswith(".py")
    )


def _source_at_ref(repo_root: Path, base_ref: str, path: Path) -> str | None:
    result = _git(repo_root, "show", f"{base_ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def _candidate_id(trigger_id: str, path: str, subject: str) -> str:
    raw = f"{trigger_id}|{path}|{subject}".encode()
    return f"QR-{hashlib.sha256(raw).hexdigest()[:12]}"


def _file_size_candidates(
    repo_root: Path,
    changed_paths: list[Path],
    base_ref: str | None,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for path in changed_paths:
        full_path = repo_root / path
        if not full_path.is_file():
            continue
        source = full_path.read_text(encoding="utf-8")
        current = effective_code_lines(source)
        if current <= FILE_LOC_REVIEW_THRESHOLD:
            continue
        previous_source = _source_at_ref(repo_root, base_ref, path) if base_ref else None
        previous = (
            effective_code_lines(previous_source)
            if previous_source is not None
            else None
        )
        candidates.append(
            {
                "candidate_id": _candidate_id(
                    "QR-FSIZE-001",
                    path.as_posix(),
                    path.name,
                ),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-FSIZE-001",
                "scope": {"path": path.as_posix(), "subject": path.name},
                "facts": [
                    {
                        "kind": "effective_file_loc",
                        "value": current,
                        "tool": "python:tokenize",
                        "interpretation": "none",
                    }
                ],
                "deltas": [
                    {
                        "kind": "effective_file_loc",
                        "before": previous,
                        "after": current,
                        "delta": None if previous is None else current - previous,
                    }
                ],
                "review_questions": [
                    (
                        "Does this file contain more than one independently changing "
                        "responsibility?"
                    ),
                    (
                        "Would extraction reduce reasoning cost without adding "
                        "forwarding ceremony?"
                    ),
                    "Is the size mostly declarative or linear rather than decision-heavy?",
                ],
            }
        )
    return candidates


def _navigation_candidates(
    repo_root: Path,
    changed_paths: list[Path],
    base_ref: str | None,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for path in changed_paths:
        full_path = repo_root / path
        if not full_path.is_file() or path.name == "__init__.py":
            continue
        source = full_path.read_text(encoding="utf-8")
        previous_source = _source_at_ref(repo_root, base_ref, path) if base_ref else None
        if previous_source is not None:
            continue
        observation = navigation_observation(path, source)
        forwarding_only = observation["forwarding_only_functions"] is True
        reexport_only = observation["reexport_only_module"] is True
        if not forwarding_only and not reexport_only:
            continue
        candidates.append(
            {
                "candidate_id": _candidate_id(
                    "QR-NAV-001",
                    path.as_posix(),
                    path.name,
                ),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-NAV-001",
                "scope": {"path": path.as_posix(), "subject": path.name},
                "facts": [
                    {
                        "kind": "one_call_forwarder_count",
                        "value": observation["one_call_forwarder_count"],
                        "tool": "python:ast",
                        "interpretation": "none",
                    },
                    {
                        "kind": "reexport_only_module",
                        "value": reexport_only,
                        "tool": "python:ast",
                        "interpretation": "none",
                    },
                ],
                "deltas": [],
                "review_questions": [
                    (
                        "Does this indirection represent a real ownership or "
                        "substitution boundary?"
                    ),
                    (
                        "Does it shorten the reasoning path or only move a "
                        "call/re-export elsewhere?"
                    ),
                    (
                        "Would keeping behavior local be easier to navigate without "
                        "weakening a boundary?"
                    ),
                ],
            }
        )
    return candidates


def _coupling_candidates(diff: dict[str, object] | None) -> list[dict[str, object]]:
    if diff is None:
        return []
    coupling = diff.get("component_coupling", {})
    if not isinstance(coupling, dict):
        return []
    added = coupling.get("added_edges", [])
    if not isinstance(added, list):
        return []
    candidates: list[dict[str, object]] = []
    for item in added:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "<unknown>"))
        target = str(item.get("target", "<unknown>"))
        subject = f"{source}->{target}"
        candidates.append(
            {
                "candidate_id": _candidate_id(
                    "QR-COUPLING-001",
                    source,
                    subject,
                ),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-COUPLING-001",
                "scope": {
                    "path": f"backend/src/jurisnexo/{source}",
                    "subject": subject,
                },
                "facts": [
                    {
                        "kind": "added_component_dependency",
                        "value": subject,
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                    {
                        "kind": "import_sites",
                        "value": item.get("import_sites", []),
                        "tool": "python:ast-import-graph",
                        "interpretation": "none",
                    },
                ],
                "deltas": [],
                "review_questions": [
                    (
                        "Does this dependency represent a real capability need and "
                        "correct ownership?"
                    ),
                    (
                        "Does it cross a trust, persistence, provider, or legal-data "
                        "authority boundary?"
                    ),
                    (
                        "Would a helper or service locator merely hide the same "
                        "dependency from the graph?"
                    ),
                ],
            }
        )
    return candidates


def _suppression_candidates(diff: dict[str, object] | None) -> list[dict[str, object]]:
    if diff is None:
        return []
    suppressions = diff.get("suppressions", {})
    if not isinstance(suppressions, dict):
        return []
    files = suppressions.get("files", [])
    if not isinstance(files, list):
        return []
    candidates: list[dict[str, object]] = []
    for item in files:
        if not isinstance(item, dict) or int(item.get("delta", 0)) <= 0:
            continue
        path = str(item.get("path", "<unknown>"))
        candidates.append(
            {
                "candidate_id": _candidate_id("QR-SUPPRESS-001", path, path),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-SUPPRESS-001",
                "scope": {"path": path, "subject": path},
                "facts": [
                    {
                        "kind": "suppression_delta",
                        "value": int(item["delta"]),
                        "tool": "python:tokenize-comments",
                        "interpretation": "none",
                    }
                ],
                "deltas": [
                    {
                        "kind": "suppression_count",
                        "before": item["before"],
                        "after": item["after"],
                        "delta": int(item["delta"]),
                    }
                ],
                "review_questions": [
                    (
                        "Is each new suppression narrowly justified by a real tool "
                        "limitation?"
                    ),
                    (
                        "Can the underlying type/lint/security/coverage issue be fixed "
                        "without obscuring intent?"
                    ),
                    (
                        "Does the suppression hide behavior that should remain visible "
                        "to a blocking gate?"
                    ),
                ],
            }
        )
    return candidates


def parse_ruff_c901(diagnostics: list[dict[str, Any]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for diagnostic in diagnostics:
        if diagnostic.get("code") != "C901":
            continue
        message = str(diagnostic.get("message", ""))
        score_match = _C901_SCORE.search(message)
        subject_match = _C901_SUBJECT.search(message)
        filename = Path(str(diagnostic.get("filename", "<unknown>")))
        try:
            path = filename.relative_to(Path.cwd()) if filename.is_absolute() else filename
        except ValueError:
            path = filename
        subject = subject_match.group("subject") if subject_match else "<function>"
        score = int(score_match.group("score")) if score_match else None
        location = diagnostic.get("location")
        line = location.get("row") if isinstance(location, dict) else None
        candidates.append(
            {
                "candidate_id": _candidate_id(
                    "QR-CPLX-001",
                    path.as_posix(),
                    subject,
                ),
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-CPLX-001",
                "scope": {
                    "path": path.as_posix(),
                    "subject": subject,
                    "line": line,
                },
                "facts": [
                    {
                        "kind": "function_mccabe",
                        "value": score,
                        "tool": "ruff:C901",
                        "interpretation": "none",
                    }
                ],
                "deltas": [],
                "review_questions": [
                    (
                        "Where does the reasoning load come from: branches, state, "
                        "ordering, or effects?"
                    ),
                    (
                        "Can decision structure be simplified without distributing it "
                        "across helpers?"
                    ),
                    (
                        "Would extraction create a real responsibility boundary and "
                        "preserve locality?"
                    ),
                ],
            }
        )
    return candidates


def run_ruff_c901(repo_root: Path, paths: list[Path]) -> list[dict[str, object]]:
    existing = [path for path in paths if (repo_root / path).is_file()]
    if not existing:
        return []
    result = subprocess.run(
        [
            "ruff",
            "check",
            "--select",
            "C901",
            "--output-format",
            "json",
            "--exit-zero",
            *[path.as_posix() for path in existing],
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Ruff produced no diagnostic"
        )
        raise RuntimeError(f"Ruff C901 sensor failed: {detail}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ruff C901 sensor returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise RuntimeError("Ruff C901 sensor returned an unexpected JSON shape")
    return parse_ruff_c901([item for item in payload if isinstance(item, dict)])


def build_report(repo_root: Path, *, base_ref: str | None = None) -> dict[str, object]:
    measurements = file_measurements(repo_root)
    coupling = component_dependency_snapshot(repo_root)
    changed_paths = _changed_python_paths(repo_root, base_ref)
    architecture_diff = (
        build_architecture_diff(repo_root, base_ref) if base_ref else None
    )
    candidates: list[dict[str, object]] = []
    candidates.extend(_file_size_candidates(repo_root, changed_paths, base_ref))
    candidates.extend(run_ruff_c901(repo_root, changed_paths))
    candidates.extend(_navigation_candidates(repo_root, changed_paths, base_ref))
    candidates.extend(_coupling_candidates(architecture_diff))
    candidates.extend(_suppression_candidates(architecture_diff))
    largest_files = sorted(
        measurements,
        key=lambda record: (
            int(record["effective_loc"]),
            str(record["path"]),
        ),
        reverse=True,
    )[:20]
    components = coupling.get("components", [])
    edges = coupling.get("edges", [])
    trigger_counts: dict[str, int] = {}
    for candidate in candidates:
        trigger = str(candidate["trigger_id"])
        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "maintainability-signals-are-non-blocking",
        "provenance": {
            "base_ref": base_ref,
            "candidate_scope": (
                "all-python-files" if base_ref is None else "changed-python-files"
            ),
            "changed_python_file_count": len(changed_paths),
        },
        "policy": {
            "file_loc_review_threshold": FILE_LOC_REVIEW_THRESHOLD,
            "mccabe_review_threshold": MCCABE_REVIEW_THRESHOLD,
            "threshold_status": "calibration-triggers-not-architecture-cliffs",
            "coupling_policy": (
                "new component edges trigger review; no numeric fan-in/fan-out cliff"
            ),
            "navigation_policy": (
                "new forwarding/re-export-only files trigger review, not automatic "
                "rejection"
            ),
            "suppression_policy": (
                "growth triggers review; deterministic lint/type/security gates remain "
                "authoritative"
            ),
            "agent_action": (
                "review ownership, locality, reasoning complexity and authority before "
                "refactoring; never game metrics"
            ),
        },
        "summary": {
            "python_file_count": len(measurements),
            "component_count": len(components) if isinstance(components, list) else 0,
            "connection_count": len(edges) if isinstance(edges, list) else 0,
            "review_candidate_count": len(candidates),
            "review_candidate_counts_by_trigger": trigger_counts,
        },
        "component_coupling": coupling,
        "largest_files": largest_files,
        "file_measurements": measurements,
        "review_candidates": candidates,
    }


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def render_summary(report: dict[str, object]) -> str:
    summary = report["summary"]
    coupling = report["component_coupling"]
    provenance = report["provenance"]
    components = coupling["components"]
    edges = coupling["edges"]
    largest = report["largest_files"]
    candidates = report["review_candidates"]
    lines = [
        "## JurisNexo engineering quality signals",
        "",
        f"Python files measured: **{summary['python_file_count']}**",
        f"Architecture components: **{summary['component_count']}**",
        f"Observed component connections: **{summary['connection_count']}**",
        f"Review candidates: **{summary['review_candidate_count']}**",
        f"Candidate scope: **{provenance['candidate_scope']}**",
        "",
        (
            "These are review signals. eLOC, C901, suppression counts and "
            "fan-in/fan-out are not blocking architecture limits."
        ),
        "",
        "### Component coupling",
        "",
    ]
    lines.extend(
        _markdown_table(
            ["Component", "Files", "eLOC", "Fan-in", "Fan-out"],
            [
                [
                    item["component"],
                    item["python_files"],
                    item["effective_loc"],
                    item["fan_in"],
                    item["fan_out"],
                ]
                for item in components
            ],
        )
    )
    lines.extend(["", "### Connections", ""])
    if edges:
        lines.extend(
            (
                f"- `{edge['source']} -> {edge['target']}` "
                f"({edge['import_site_count']} import site(s))"
            )
            for edge in edges
        )
    else:
        lines.append("- No cross-component Python import edges detected.")
    lines.extend(["", "### Largest Python files by effective LOC", ""])
    lines.extend(
        _markdown_table(
            ["Path", "Category", "eLOC"],
            [
                [item["path"], item["category"], item["effective_loc"]]
                for item in largest[:15]
            ],
        )
    )
    if candidates:
        lines.extend(
            [
                "",
                "### Review candidates",
                "",
                (
                    "A candidate is not a defect. Semantic review decides "
                    "HEALTHY_AS_IS vs a concrete concern."
                ),
                "",
            ]
        )
        for item in candidates:
            facts = item.get("facts", [])
            fact = (
                facts[0]
                if isinstance(facts, list)
                and facts
                and isinstance(facts[0], dict)
                else {}
            )
            scope = item.get("scope", {})
            lines.append(
                f"- `{item['trigger_id']}` `{scope.get('path')}` :: "
                f"`{scope.get('subject')}` — {fact.get('kind')}="
                f"{fact.get('value')}"
            )
    return "\n".join(lines)


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_github_summary(text: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-ref")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    try:
        report = build_report(repo_root, base_ref=args.base_ref)
    except (
        OSError,
        RuntimeError,
        SyntaxError,
        tokenize.TokenError,
        ValueError,
    ) as exc:
        print(f"[ENGINEERING-QUALITY-ERROR] evidence collection failed: {exc}")
        return 2
    write_report(report, output)
    summary = render_summary(report)
    print(summary)
    write_github_summary(summary)
    print(f"Engineering quality evidence: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
