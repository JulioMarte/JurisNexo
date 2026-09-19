from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
SRC_ROOT = BACKEND_ROOT / "src" / "jurisnexo"
BENCHMARK_ROOT = REPO_ROOT / "benchmark"

DATABASE_PREFIXES = ("psycopg", "sqlalchemy", "asyncpg", "sqlite3")
CONCRETE_PROVIDER_PREFIXES = (
    "agents",
    "openai",
    "google.generativeai",
    "google.genai",
)
PERSISTENCE_AUTHORITY_PREFIXES = (
    "jurisnexo.platform.db",
    "jurisnexo.ingestion.observation_persistence",
    "jurisnexo.corpus.canonical_commit",
)
AGENT_ROLE_DIRECTORIES = {"agents", "agent_runtime"}
AGENT_ROLE_SUFFIXES = ("_agent", "_auditor")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _matches_prefix(import_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        import_name == prefix or import_name.startswith(f"{prefix}.") for prefix in prefixes
    )


def _is_persistence_authority(import_name: str) -> bool:
    return bool(
        _matches_prefix(import_name, PERSISTENCE_AUTHORITY_PREFIXES)
        or ".adapters.db" in import_name
        or import_name.endswith(".adapters.db")
    )


def _module_for_path(path: Path) -> str | None:
    try:
        relative = path.relative_to(BACKEND_ROOT / "src")
    except ValueError:
        return None
    if path.name == "__init__.py":
        parts = relative.parent.parts
    else:
        parts = (*relative.parent.parts, path.stem)
    return ".".join(parts)


def _path_for_module(module_name: str) -> Path | None:
    if not module_name.startswith("jurisnexo"):
        return None
    relative = Path(*module_name.split("."))
    module_path = BACKEND_ROOT / "src" / relative.with_suffix(".py")
    if module_path.is_file():
        return module_path
    package_path = BACKEND_ROOT / "src" / relative / "__init__.py"
    if package_path.is_file():
        return package_path
    return None


def _is_agent_runtime_surface(path: Path) -> bool:
    relative_parts = path.relative_to(SRC_ROOT).parts
    role_parts = set(relative_parts[:-1])
    stem = path.stem
    return bool(
        role_parts & AGENT_ROLE_DIRECTORIES
        or stem.startswith("agent")
        or stem.endswith(AGENT_ROLE_SUFFIXES)
    )


def _agent_runtime_files() -> list[Path]:
    return [path for path in SRC_ROOT.rglob("*.py") if _is_agent_runtime_surface(path)]


def _agent_benchmark_entrypoints() -> list[Path]:
    if not BENCHMARK_ROOT.is_dir():
        return []
    return [
        path
        for path in BENCHMARK_ROOT.rglob("*.py")
        if "agent" in path.stem or "auditor" in path.stem
    ]


def _transitive_database_paths(start: Path) -> list[str]:
    """Return import chains from one agent surface to database/persistence authority."""

    start_module = _module_for_path(start) or str(start.relative_to(REPO_ROOT))
    queue: deque[tuple[Path, tuple[str, ...]]] = deque([(start, (start_module,))])
    visited: set[Path] = set()
    violations: list[str] = []

    while queue:
        path, chain = queue.popleft()
        if path in visited:
            continue
        visited.add(path)

        for import_name in _imports(path):
            if _matches_prefix(import_name, DATABASE_PREFIXES) or _is_persistence_authority(
                import_name
            ):
                violations.append(" -> ".join((*chain, import_name)))
                continue

            internal_path = _path_for_module(import_name)
            if internal_path is None or internal_path in visited:
                continue
            queue.append((internal_path, (*chain, import_name)))

    return violations


def test_agent_runtime_surface_detection_is_role_based_not_package_snapshot() -> None:
    assert _is_agent_runtime_surface(SRC_ROOT / "ingestion" / "structure_agent.py")
    assert _is_agent_runtime_surface(SRC_ROOT / "ingestion" / "extraction_auditor.py")
    assert _is_agent_runtime_surface(SRC_ROOT / "agents" / "research.py")
    assert _is_agent_runtime_surface(SRC_ROOT / "ingestion" / "agentic_discovery.py")

    assert not _is_agent_runtime_surface(SRC_ROOT / "ingestion" / "observation_persistence.py")
    assert not _is_agent_runtime_surface(SRC_ROOT / "research" / "repository.py")


def test_agent_runtime_surfaces_do_not_import_database_drivers() -> None:
    violations: list[str] = []
    for path in _agent_runtime_files():
        for import_name in _imports(path):
            if _matches_prefix(import_name, DATABASE_PREFIXES):
                violations.append(f"{path.relative_to(BACKEND_ROOT)} -> {import_name}")

    assert not violations, "\n".join(
        [
            "Agent/runtime code gained direct database authority.",
            *[f"- {item}" for item in violations],
            "",
            "Use a typed Document Workspace or Corpus API/application capability instead. "
            "Do not grant agents generic SQL/driver access. If the architecture is intentionally "
            "changing, update the normative docs/guarantee first rather than weakening this test.",
        ]
    )


def test_agent_runtime_has_no_transitive_path_to_database_authority() -> None:
    violations: list[str] = []
    for path in _agent_runtime_files():
        for chain in _transitive_database_paths(path):
            violations.append(f"{path.relative_to(BACKEND_ROOT)}: {chain}")

    assert not violations, "\n".join(
        [
            "An agent/runtime surface can reach database authority through internal imports.",
            *[f"- {item}" for item in violations],
            "",
            "The LLM boundary must remain: agent -> typed workspace/capability -> application "
            "service -> persistence adapter. Agents may receive data or narrow capabilities, "
            "but they must never gain a transitive import path to SQL drivers, platform.db, "
            "DB adapters, observation persistence, or canonical commit code.",
        ]
    )


def test_agent_benchmark_entrypoints_cannot_reach_database_authority() -> None:
    violations: list[str] = []
    for path in _agent_benchmark_entrypoints():
        for chain in _transitive_database_paths(path):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {chain}")

    assert not violations, "\n".join(
        [
            "An agent benchmark gained a database/persistence dependency.",
            *[f"- {item}" for item in violations],
            "",
            "Agent benchmarks must exercise the same production security boundary as the runtime. "
            "Materialize an immutable document/corpus fixture first, then give the model only "
            "typed read capabilities over that fixture.",
        ]
    )


def test_model_provider_contract_does_not_depend_on_concrete_provider_sdk() -> None:
    contract = SRC_ROOT / "model_providers" / "contracts.py"
    assert contract.is_file(), "The current provider-neutral contract surface is missing."

    violations = [
        import_name
        for import_name in _imports(contract)
        if _matches_prefix(import_name, CONCRETE_PROVIDER_PREFIXES + DATABASE_PREFIXES)
    ]

    assert not violations, (
        "Provider-neutral contracts imported concrete runtime/provider/database dependencies: "
        f"{violations}. Keep framework/provider SDK objects in adapters/runtime composition, not "
        "in durable provider contracts."
    )
