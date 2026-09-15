from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_metrics import (  # noqa: E402
    component_dependency_snapshot,
    component_dependency_snapshot_from_sources,
    effective_code_lines,
    navigation_observation,
    suppression_observation,
)

SCHEMA_VERSION = "jurisnexo-architecture-diff/v1"
DEFAULT_OUTPUT = Path(".ci/architecture-diff.json")
PYTHON_ROOTS = (
    "backend/src",
    "backend/tests",
    "backend/migrations",
    "backend/scripts",
)
PACKAGE_PREFIX = "backend/src/jurisnexo"


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


def _sha(repo_root: Path, ref: str) -> str:
    return _git(repo_root, "rev-parse", ref).stdout.strip()


def _source_at_ref(repo_root: Path, ref: str, path: Path) -> str | None:
    result = _git(repo_root, "show", f"{ref}:{path.as_posix()}", check=False)
    return result.stdout if result.returncode == 0 else None


def _package_sources_at_ref(repo_root: Path, ref: str) -> dict[Path, str]:
    listing = _git(
        repo_root,
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        PACKAGE_PREFIX,
    )
    sources: dict[Path, str] = {}
    for item in listing.stdout.splitlines():
        if not item.endswith(".py"):
            continue
        path = Path(item)
        source = _source_at_ref(repo_root, ref, path)
        if source is not None:
            sources[path] = source
    return sources


def _changed_python_paths(repo_root: Path, base_ref: str) -> list[Path]:
    result = _git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=ACMRD",
        f"{base_ref}...HEAD",
        "--",
        *PYTHON_ROOTS,
    )
    return sorted({Path(item) for item in result.stdout.splitlines() if item.endswith(".py")})


def _edge_map(snapshot: dict[str, object]) -> dict[tuple[str, str], dict[str, Any]]:
    raw = snapshot.get("edges", [])
    records: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(raw, list):
        return records
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if isinstance(source, str) and isinstance(target, str):
            records[(source, target)] = item
    return records


def _component_map(snapshot: dict[str, object]) -> dict[str, dict[str, Any]]:
    raw = snapshot.get("components", [])
    records: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return records
    for item in raw:
        if not isinstance(item, dict):
            continue
        component = item.get("component")
        if isinstance(component, str):
            records[component] = item
    return records


def _coupling_diff(base: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    before = _edge_map(base)
    after = _edge_map(current)
    before_pairs = set(before)
    after_pairs = set(after)
    site_deltas: list[dict[str, object]] = []
    for edge in sorted(before_pairs & after_pairs):
        before_sites = set(str(item) for item in before[edge].get("import_sites", []))
        after_sites = set(str(item) for item in after[edge].get("import_sites", []))
        added_sites = sorted(after_sites - before_sites)
        removed_sites = sorted(before_sites - after_sites)
        if added_sites or removed_sites:
            site_deltas.append(
                {
                    "source": edge[0],
                    "target": edge[1],
                    "before_import_site_count": len(before_sites),
                    "after_import_site_count": len(after_sites),
                    "added_import_sites": added_sites,
                    "removed_import_sites": removed_sites,
                    "interpretation": "none",
                }
            )
    return {
        "added_edges": [
            {
                "source": source,
                "target": target,
                "import_sites": after[(source, target)]["import_sites"],
            }
            for source, target in sorted(after_pairs - before_pairs)
        ],
        "removed_edges": [
            {
                "source": source,
                "target": target,
                "import_sites": before[(source, target)]["import_sites"],
            }
            for source, target in sorted(before_pairs - after_pairs)
        ],
        "import_site_deltas": site_deltas,
    }


def _component_deltas(
    base: dict[str, object],
    current: dict[str, object],
) -> list[dict[str, object]]:
    before = _component_map(base)
    after = _component_map(current)
    deltas: list[dict[str, object]] = []
    for component in sorted(set(before) | set(after)):
        old = before.get(component, {})
        new = after.get(component, {})
        values: dict[str, dict[str, int]] = {}
        changed = False
        for field in ("python_files", "effective_loc", "fan_in", "fan_out"):
            old_value = int(old.get(field, 0))
            new_value = int(new.get(field, 0))
            values[field] = {
                "before": old_value,
                "after": new_value,
                "delta": new_value - old_value,
            }
            changed = changed or old_value != new_value
        if changed:
            deltas.append({"component": component, **values, "interpretation": "none"})
    return deltas


def _file_deltas(
    repo_root: Path,
    base_ref: str,
    paths: list[Path],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        before_source = _source_at_ref(repo_root, base_ref, path)
        after_path = repo_root / path
        after_source = after_path.read_text(encoding="utf-8") if after_path.is_file() else None
        before = effective_code_lines(before_source) if before_source is not None else 0
        after = effective_code_lines(after_source) if after_source is not None else 0
        if before_source is None:
            status = "added"
        elif after_source is None:
            status = "deleted"
        else:
            status = "modified"
        records.append(
            {
                "path": path.as_posix(),
                "status": status,
                "effective_loc": {"before": before, "after": after, "delta": after - before},
                "interpretation": "none",
            }
        )
    return records


def _suppression_diff(
    repo_root: Path,
    base_ref: str,
    paths: list[Path],
) -> dict[str, object]:
    files: list[dict[str, object]] = []
    total_before = 0
    total_after = 0
    for path in paths:
        before_source = _source_at_ref(repo_root, base_ref, path) or ""
        after_path = repo_root / path
        after_source = after_path.read_text(encoding="utf-8") if after_path.is_file() else ""
        before = suppression_observation(before_source)
        after = suppression_observation(after_source)
        before_total = int(before["total"])
        after_total = int(after["total"])
        total_before += before_total
        total_after += after_total
        if before != after:
            files.append(
                {
                    "path": path.as_posix(),
                    "before": before,
                    "after": after,
                    "delta": after_total - before_total,
                    "interpretation": "none",
                }
            )
    return {
        "scope": "changed-python-files",
        "before": total_before,
        "after": total_after,
        "delta": total_after - total_before,
        "files": files,
        "markers": ["noqa", "type: ignore", "nosec", "pragma: no cover"],
        "interpretation": "none",
    }


def _empty_navigation(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "function_count": 0,
        "one_call_forwarder_count": 0,
        "forwarding_only_functions": False,
        "reexport_only_module": False,
    }


def _navigation_diff(
    repo_root: Path,
    base_ref: str,
    paths: list[Path],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        before_source = _source_at_ref(repo_root, base_ref, path)
        after_path = repo_root / path
        after_source = after_path.read_text(encoding="utf-8") if after_path.is_file() else None
        try:
            before = (
                navigation_observation(path, before_source)
                if before_source is not None
                else _empty_navigation(path)
            )
            after = (
                navigation_observation(path, after_source)
                if after_source is not None
                else _empty_navigation(path)
            )
        except SyntaxError:
            continue
        before_forwarders = int(before["one_call_forwarder_count"])
        after_forwarders = int(after["one_call_forwarder_count"])
        before_reexport = before["reexport_only_module"] is True
        after_reexport = after["reexport_only_module"] is True
        before_forwarding_only = before["forwarding_only_functions"] is True
        after_forwarding_only = after["forwarding_only_functions"] is True
        if (
            before_forwarders == after_forwarders
            and before_reexport == after_reexport
            and before_forwarding_only == after_forwarding_only
        ):
            continue
        records.append(
            {
                "path": path.as_posix(),
                "one_call_forwarder_count": {
                    "before": before_forwarders,
                    "after": after_forwarders,
                    "delta": after_forwarders - before_forwarders,
                },
                "forwarding_only_functions": {
                    "before": before_forwarding_only,
                    "after": after_forwarding_only,
                },
                "reexport_only_module": {"before": before_reexport, "after": after_reexport},
                "interpretation": "none",
            }
        )
    return records


def build_architecture_diff(repo_root: Path, base_ref: str) -> dict[str, object]:
    paths = _changed_python_paths(repo_root, base_ref)
    base_sources = _package_sources_at_ref(repo_root, base_ref)
    base_coupling = component_dependency_snapshot_from_sources(base_sources)
    current_coupling = component_dependency_snapshot(repo_root)
    tested_sha = _sha(repo_root, "HEAD")
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "informational-review-evidence",
        "provenance": {
            "base_ref": base_ref,
            "base_sha": _sha(repo_root, base_ref),
            "source_head_sha": os.environ.get("QUALITY_SOURCE_HEAD_SHA", tested_sha),
            "tested_sha": tested_sha,
            "test_mode": os.environ.get("QUALITY_TEST_MODE", "BRANCH_HEAD"),
        },
        "changed_python_paths": [path.as_posix() for path in paths],
        "component_coupling": _coupling_diff(base_coupling, current_coupling),
        "component_deltas": _component_deltas(base_coupling, current_coupling),
        "file_deltas": _file_deltas(repo_root, base_ref, paths),
        "suppressions": _suppression_diff(repo_root, base_ref, paths),
        "navigation": _navigation_diff(repo_root, base_ref, paths),
        "review_contract": {
            "no_synthetic_score": True,
            "no_numeric_coupling_cliff": True,
            "new_edges_require_context": True,
            "file_growth_is_evidence_not_defect": True,
            "suppression_growth_is_evidence_not_defect": True,
            "navigation_growth_is_evidence_not_defect": True,
        },
    }


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def render_summary(payload: dict[str, object]) -> str:
    coupling = payload["component_coupling"]
    provenance = payload["provenance"]
    component_deltas = payload["component_deltas"]
    file_deltas = payload["file_deltas"]
    suppressions = payload["suppressions"]
    navigation = payload["navigation"]
    assert isinstance(coupling, dict)
    assert isinstance(provenance, dict)
    assert isinstance(component_deltas, list)
    assert isinstance(file_deltas, list)
    assert isinstance(suppressions, dict)
    assert isinstance(navigation, list)
    added = coupling.get("added_edges", [])
    removed = coupling.get("removed_edges", [])
    sites = coupling.get("import_site_deltas", [])
    lines = [
        "## JurisNexo architecture diff",
        "",
        f"Base: `{provenance.get('base_sha')}`",
        f"Source head: `{provenance.get('source_head_sha')}`",
        f"Tested tree: `{provenance.get('tested_sha')}`",
        "",
        f"Added component edges: **{len(added) if isinstance(added, list) else 0}**",
        f"Removed component edges: **{len(removed) if isinstance(removed, list) else 0}**",
        f"Import-site deltas: **{len(sites) if isinstance(sites, list) else 0}**",
        f"Component metric deltas: **{len(component_deltas)}**",
        f"Changed Python files: **{len(file_deltas)}**",
        f"Suppression delta: **{int(suppressions.get('delta', 0)):+}**",
        f"Navigation-shape deltas: **{len(navigation)}**",
        "",
        (
            "No architecture score is computed. Deltas are review evidence; "
            "HARD invariants remain independently blocking."
        ),
    ]
    if isinstance(added, list) and added:
        lines.extend(["", "### Added connections", ""])
        lines.extend(
            f"- `+ {item['source']} -> {item['target']}`"
            for item in added
            if isinstance(item, dict)
        )
    if isinstance(removed, list) and removed:
        lines.extend(["", "### Removed connections", ""])
        lines.extend(
            f"- `- {item['source']} -> {item['target']}`"
            for item in removed
            if isinstance(item, dict)
        )
    if component_deltas:
        lines.extend(["", "### Component deltas", ""])
        lines.extend(
            _table(
                ["Component", "Files Δ", "eLOC Δ", "Fan-in Δ", "Fan-out Δ"],
                [
                    [
                        item["component"],
                        item["python_files"]["delta"],
                        item["effective_loc"]["delta"],
                        item["fan_in"]["delta"],
                        item["fan_out"]["delta"],
                    ]
                    for item in component_deltas
                    if isinstance(item, dict)
                ],
            )
        )
    if file_deltas:
        lines.extend(["", "### Python file eLOC deltas", ""])
        ranked = sorted(
            (item for item in file_deltas if isinstance(item, dict)),
            key=lambda item: abs(int(item["effective_loc"]["delta"])),
            reverse=True,
        )[:20]
        lines.extend(
            _table(
                ["Path", "Status", "Before", "After", "Δ"],
                [
                    [
                        item["path"],
                        item["status"],
                        item["effective_loc"]["before"],
                        item["effective_loc"]["after"],
                        item["effective_loc"]["delta"],
                    ]
                    for item in ranked
                ],
            )
        )
    return "\n".join(lines)


def _write_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    try:
        payload = build_architecture_diff(repo_root, args.base_ref)
    except (
        OSError,
        RuntimeError,
        SyntaxError,
        tokenize.TokenError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        print(f"[ARCHITECTURE-DIFF-ERROR] evidence collection failed: {exc}")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = render_summary(payload)
    print(summary)
    _write_summary(summary)
    print(f"Architecture diff evidence: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
