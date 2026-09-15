from __future__ import annotations

import ast
import io
import tokenize
from collections import defaultdict
from pathlib import Path

IGNORED_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
}
PYTHON_SCAN_ROOTS = (
    Path("backend/src"),
    Path("backend/tests"),
    Path("backend/migrations"),
    Path("backend/scripts"),
)
PACKAGE_ROOT = Path("backend/src/jurisnexo")
NON_COMPONENT_NAMES = {"__pycache__"}


def effective_code_lines(source: str) -> int:
    """Count Python lines containing real tokens rather than comments/whitespace."""
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in IGNORED_TOKEN_TYPES:
            continue
        lines.update(range(token.start[0], token.end[0] + 1))
    return len(lines)


def python_files(repo_root: Path) -> list[Path]:
    files: set[Path] = set()
    for relative_root in PYTHON_SCAN_ROOTS:
        root = repo_root / relative_root
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in {".venv", "__pycache__", "build", "dist"} for part in path.parts):
                continue
            files.add(path)
    return sorted(files)


def classify_path(repo_root: Path, path: Path) -> str:
    relative = path.relative_to(repo_root)
    parts = relative.parts
    if parts[:3] == ("backend", "src", "jurisnexo"):
        return "production"
    if parts[:2] == ("backend", "tests"):
        return "tests"
    if parts[:2] == ("backend", "migrations"):
        return "migrations"
    if parts[:2] == ("backend", "scripts"):
        return "scripts"
    return "python_other"


def component_for_path(repo_root: Path, path: Path) -> str | None:
    package_root = repo_root / PACKAGE_ROOT
    try:
        relative = path.relative_to(package_root)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    component = relative.parts[0]
    if component in NON_COMPONENT_NAMES or component.startswith("__"):
        return None
    return component


def discover_components(repo_root: Path) -> set[str]:
    package_root = repo_root / PACKAGE_ROOT
    if not package_root.is_dir():
        return set()
    components: set[str] = set()
    for child in package_root.iterdir():
        if not child.is_dir() or child.name in NON_COMPONENT_NAMES or child.name.startswith("__"):
            continue
        if any(child.rglob("*.py")):
            components.add(child.name)
    return components


def _absolute_import_targets(node: ast.Import | ast.ImportFrom) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        names = [node.module] if node.module else []
        if node.module == "jurisnexo":
            names.extend(f"jurisnexo.{alias.name}" for alias in node.names)
    for name in names:
        if not name:
            continue
        parts = name.split(".")
        if len(parts) >= 2 and parts[0] == "jurisnexo":
            targets.add(parts[1])
    return targets


def _relative_import_target(path: Path, package_root: Path, node: ast.ImportFrom) -> str | None:
    if node.level <= 0:
        return None
    relative = path.relative_to(package_root)
    package = list(relative.parts[:-1])
    climb = node.level - 1
    if climb > len(package):
        return None
    resolved = package[: len(package) - climb]
    if node.module:
        resolved.extend(node.module.split("."))
    if not resolved:
        return None
    return resolved[0]


def component_import_targets(repo_root: Path, path: Path, source: str) -> set[str]:
    source_component = component_for_path(repo_root, path)
    if source_component is None:
        return set()
    package_root = repo_root / PACKAGE_ROOT
    known_components = discover_components(repo_root)
    tree = ast.parse(source, filename=path.as_posix())
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(_absolute_import_targets(node))
        elif isinstance(node, ast.ImportFrom):
            targets.update(_absolute_import_targets(node))
            relative_target = _relative_import_target(path, package_root, node)
            if relative_target is not None:
                targets.add(relative_target)
    return {target for target in targets if target in known_components and target != source_component}


def component_dependency_snapshot(repo_root: Path) -> dict[str, object]:
    components = discover_components(repo_root)
    package_root = repo_root / PACKAGE_ROOT
    edge_sites: dict[tuple[str, str], set[str]] = defaultdict(set)
    component_files: dict[str, set[str]] = defaultdict(set)
    component_loc: dict[str, int] = defaultdict(int)

    for path in sorted(package_root.rglob("*.py")) if package_root.is_dir() else []:
        component = component_for_path(repo_root, path)
        if component is None:
            continue
        relative = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8")
        component_files[component].add(relative)
        component_loc[component] += effective_code_lines(source)
        for target in component_import_targets(repo_root, path, source):
            edge_sites[(component, target)].add(relative)

    edges = set(edge_sites)
    component_records: list[dict[str, object]] = []
    for component in sorted(components):
        inbound = sorted(source for source, target in edges if target == component)
        outbound = sorted(target for source, target in edges if source == component)
        component_records.append(
            {
                "component": component,
                "python_files": len(component_files.get(component, set())),
                "effective_loc": component_loc.get(component, 0),
                "fan_in": len(inbound),
                "fan_out": len(outbound),
                "inbound_components": inbound,
                "outbound_components": outbound,
            }
        )

    edge_records = [
        {
            "source": source,
            "target": target,
            "import_site_count": len(edge_sites[(source, target)]),
            "import_sites": sorted(edge_sites[(source, target)]),
        }
        for source, target in sorted(edges)
    ]
    return {"components": component_records, "edges": edge_records}


def file_measurements(repo_root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in python_files(repo_root):
        source = path.read_text(encoding="utf-8")
        records.append(
            {
                "path": path.relative_to(repo_root).as_posix(),
                "category": classify_path(repo_root, path),
                "effective_loc": effective_code_lines(source),
                "bytes": path.stat().st_size,
            }
        )
    return records
