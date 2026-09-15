from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tokenize
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import component_dependency_snapshot, file_measurements  # noqa: E402

SCHEMA_VERSION = "jurisnexo-engineering-quality/v1"
FILE_LOC_REVIEW_THRESHOLD = 120
DEFAULT_OUTPUT = Path(".ci/engineering-quality.json")


def _changed_python_paths(repo_root: Path, base_ref: str | None) -> set[str] | None:
    if not base_ref:
        return None
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}...HEAD",
            "--",
            "backend",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git diff failed"
        raise RuntimeError(f"cannot determine changed Python files: {detail}")
    return {path for path in result.stdout.splitlines() if path.endswith(".py")}


def build_report(repo_root: Path, *, base_ref: str | None = None) -> dict[str, object]:
    measurements = file_measurements(repo_root)
    coupling = component_dependency_snapshot(repo_root)
    changed_paths = _changed_python_paths(repo_root, base_ref)
    candidate_measurements = (
        measurements
        if changed_paths is None
        else [record for record in measurements if str(record["path"]) in changed_paths]
    )
    candidates = [
        {
            "classification": "REVIEW_CANDIDATE",
            "trigger_id": "QR-FSIZE-001",
            "path": str(record["path"]),
            "effective_loc": int(record["effective_loc"]),
            "review_questions": [
                "Does this file contain more than one independently changing responsibility?",
                "Would extraction reduce reasoning cost without adding forwarding ceremony?",
                "Is the size mostly declarative or linear rather than decision-heavy?",
            ],
        }
        for record in candidate_measurements
        if int(record["effective_loc"]) > FILE_LOC_REVIEW_THRESHOLD
    ]
    largest_files = sorted(
        measurements,
        key=lambda record: (int(record["effective_loc"]), str(record["path"])),
        reverse=True,
    )[:20]
    components = coupling.get("components", [])
    edges = coupling.get("edges", [])
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "maintainability-signals-are-non-blocking",
        "provenance": {
            "base_ref": base_ref,
            "candidate_scope": "all-python-files" if changed_paths is None else "changed-python-files",
            "changed_python_file_count": (
                None if changed_paths is None else len(changed_paths)
            ),
        },
        "policy": {
            "file_loc_review_threshold": FILE_LOC_REVIEW_THRESHOLD,
            "file_loc_threshold_status": "review-signal-not-architecture-cliff",
            "coupling_policy": (
                "all current component import edges are observable; "
                "no numeric fan-in/fan-out cliff"
            ),
            "agent_action": (
                "review ownership/locality before refactoring; never split or hide "
                "dependencies solely to lower metrics"
            ),
        },
        "summary": {
            "python_file_count": len(measurements),
            "component_count": len(components) if isinstance(components, list) else 0,
            "connection_count": len(edges) if isinstance(edges, list) else 0,
            "file_size_review_candidates": len(candidates),
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
        f"File-size review candidates: **{summary['file_size_review_candidates']}**",
        f"Candidate scope: **{provenance['candidate_scope']}**",
        "",
        (
            "These are maintainability/review signals. File size and fan-in/fan-out "
            "are not blocking architecture limits."
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
            f"- `{edge['source']} -> {edge['target']}` "
            f"({edge['import_site_count']} import site(s))"
            for edge in edges
        )
    else:
        lines.append("- No cross-component Python import edges detected.")

    lines.extend(["", "### Largest Python files by effective LOC", ""])
    lines.extend(
        _markdown_table(
            ["Path", "Category", "eLOC"],
            [[item["path"], item["category"], item["effective_loc"]] for item in largest[:15]],
        )
    )
    if candidates:
        lines.extend(
            [
                "",
                "### Review candidates",
                "",
                (
                    "A candidate is not a defect. Review responsibility, locality and "
                    "reasoning cost before changing code."
                ),
                "",
            ]
        )
        lines.extend(
            f"- `QR-FSIZE-001` `{item['path']}`: {item['effective_loc']} eLOC"
            for item in candidates
        )
    return "\n".join(lines)


def write_report(report: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_github_summary(text: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
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
    except (OSError, RuntimeError, SyntaxError, tokenize.TokenError, ValueError) as exc:
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
