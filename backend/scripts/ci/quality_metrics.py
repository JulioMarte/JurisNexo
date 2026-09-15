from __future__ import annotations

import ast
import io
import tokenize
from collections import Counter, defaultdict
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
SUPPRESSION_MARKERS = {
    "noqa": "noqa",
    "type_ignore": "type: ignore",
    "nosec": "nosec",
    "pragma_no_cover": "pragma: no cover",
}


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
            if any(
                part in {".venv", "__pycache__", "build", "dist"}
                for part in path.parts
            ):
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


def _component_from_relative_path(path: Path) -> str | None:
    parts = path.parts
    package_parts = PACKAGE_ROOT.parts
    if parts[: len(package_parts)] != package_parts:
        return None
    remainder = parts[len(package_parts) :]
    if len(remainder) < 2:
        return None
    component = remainder[0]
    if component in NON_COMPONENT_NAMES or component.startswith("__"):
        return None
    return component


def component_for_path(repo_root: Path, path: Path) -> str | None:
    return _component_from_relative_path(path.relative_to(repo_root))


def discover_components(repo_root: Path) -> set[str]:
    package_root = repo_root / PACKAGE_ROOT
    if not package_root.is_dir():
        return set()
    components: set[str] = set()
    for child in package_root.iterdir():
        if (
            not child.is_dir()
            or child.name in NON_COMPONENT_NAMES
            or child.name.startswith("__")
        ):
            continue
        if any(child.rglob("*.py")):
            components.add(child.name)
    return components


def discover_components_from_sources(sources: dict[Path, str]) -> set[str]:
    return {
        component
        for path in sources
        if (component := _component_from_relative_path(path)) is not None
    }


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


def _relative_import_target(relative_path: Path, node: ast.ImportFrom) -> str | None:
    if node.level <= 0:
        return None
    package_relative = relative_path.relative_to(PACKAGE_ROOT)
    package = list(package_relative.parts[:-1])
    climb = node.level - 1
    if climb > len(package):
        return None
    resolved = package[: len(package) - climb]
    if node.module:
        resolved.extend(node.module.split("."))
    if not resolved:
        return None
    return resolved[0]


def component_import_targets_from_source(
    relative_path: Path,
    source: str,
    known_components: set[str],
) -> set[str]:
    source_component = _component_from_relative_path(relative_path)
    if source_component is None:
        return set()
    tree = ast.parse(source, filename=relative_path.as_posix())
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(_absolute_import_targets(node))
        elif isinstance(node, ast.ImportFrom):
            targets.update(_absolute_import_targets(node))
            relative_target = _relative_import_target(relative_path, node)
            if relative_target is not None:
                targets.add(relative_target)
    return {
        target
        for target in targets
        if target in known_components and target != source_component
    }


def component_import_targets(repo_root: Path, path: Path, source: str) -> set[str]:
    return component_import_targets_from_source(
        path.relative_to(repo_root),
        source,
        discover_components(repo_root),
    )


def component_dependency_snapshot_from_sources(
    sources: dict[Path, str],
) -> dict[str, object]:
    """Build a component graph from repo-relative Python source snapshots."""
    components = discover_components_from_sources(sources)
    edge_sites: dict[tuple[str, str], set[str]] = defaultdict(set)
    component_files: dict[str, set[str]] = defaultdict(set)
    component_loc: dict[str, int] = defaultdict(int)

    for relative_path, source in sorted(
        sources.items(),
        key=lambda item: item[0].as_posix(),
    ):
        component = _component_from_relative_path(relative_path)
        if component is None:
            continue
        path_text = relative_path.as_posix()
        component_files[component].add(path_text)
        component_loc[component] += effective_code_lines(source)
        for target in component_import_targets_from_source(
            relative_path,
            source,
            components,
        ):
            edge_sites[(component, target)].add(path_text)

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


def component_dependency_snapshot(repo_root: Path) -> dict[str, object]:
    package_root = repo_root / PACKAGE_ROOT
    sources = {
        path.relative_to(repo_root): path.read_text(encoding="utf-8")
        for path in sorted(package_root.rglob("*.py"))
        if package_root.is_dir()
    }
    return component_dependency_snapshot_from_sources(sources)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_all_assignment(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == "__all__"
    return False


def _is_one_call_forwarder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [statement for statement in node.body if not _is_docstring(statement)]
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Return):
        return isinstance(statement.value, (ast.Call, ast.Await)) and (
            not isinstance(statement.value, ast.Await)
            or isinstance(statement.value.value, ast.Call)
        )
    if isinstance(statement, ast.Expr):
        value = statement.value
        return isinstance(value, ast.Call) or (
            isinstance(value, ast.Await) and isinstance(value.value, ast.Call)
        )
    return False


def navigation_observation(relative_path: Path, source: str) -> dict[str, object]:
    """Observe indirection shape without assigning a maintainability verdict."""
    tree = ast.parse(source, filename=relative_path.as_posix())
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    forwarders = [node for node in functions if _is_one_call_forwarder(node)]
    meaningful_top_level = [node for node in tree.body if not _is_docstring(node)]
    import_count = sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        for node in meaningful_top_level
    )
    reexport_only = bool(meaningful_top_level) and import_count > 0 and all(
        isinstance(node, (ast.Import, ast.ImportFrom)) or _is_all_assignment(node)
        for node in meaningful_top_level
    )
    return {
        "path": relative_path.as_posix(),
        "function_count": len(functions),
        "one_call_forwarder_count": len(forwarders),
        "forwarding_only_functions": bool(functions) and len(forwarders) == len(functions),
        "reexport_only_module": reexport_only,
    }


def suppression_observation(source: str) -> dict[str, object]:
    """Count recognized suppression markers in comments, not arbitrary strings."""
    counts: Counter[str] = Counter()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        comments = [
            token.string.lower()
            for token in tokens
            if token.type == tokenize.COMMENT
        ]
    except tokenize.TokenError:
        comments = []
    for comment in comments:
        for name, marker in SUPPRESSION_MARKERS.items():
            if marker in comment:
                counts[name] += 1
    normalized = {name: counts.get(name, 0) for name in SUPPRESSION_MARKERS}
    return {"counts": normalized, "total": sum(normalized.values())}


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
