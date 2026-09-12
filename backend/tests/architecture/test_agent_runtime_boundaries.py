from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = BACKEND_ROOT / "src" / "jurisnexo"

DATABASE_PREFIXES = ("psycopg", "sqlalchemy", "asyncpg", "sqlite3")
CONCRETE_PROVIDER_PREFIXES = (
    "agents",
    "openai",
    "google.generativeai",
    "google.genai",
)
AGENT_ROLE_DIRECTORIES = {"agents", "agent_runtime", "research"}
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
