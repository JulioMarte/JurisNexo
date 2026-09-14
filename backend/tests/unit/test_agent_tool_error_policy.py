from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def _source_root() -> Path:
    return Path(__file__).parents[2] / "src" / "jurisnexo"


def _tool_decorator(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Call | None:
    for decorator in function.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "tool"
        ):
            return decorator
    return None


def test_every_agents_sdk_tool_declares_non_null_failure_policy() -> None:
    source_root = _source_root()
    violations: list[str] = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorator = _tool_decorator(node)
            if decorator is None:
                continue
            policy = next(
                (
                    keyword.value
                    for keyword in decorator.keywords
                    if keyword.arg == "failure_error_function"
                ),
                None,
            )
            if policy is None or (
                isinstance(policy, ast.Constant) and policy.value is None
            ):
                violations.append(f"{path.relative_to(source_root)}::{node.name}")

    assert violations == [], (
        "Every @tool must explicitly classify failures. Recoverable domain/request errors should "
        "be returned to the model; unexpected runtime/invariant failures should re-raise. Unsafe "
        f"tools: {violations}"
    )


def test_source_grounded_ingestion_agents_use_repairable_finalizer_tools() -> None:
    ingestion_root = _source_root() / "ingestion"
    violations: list[str] = []

    for path in ingestion_root.glob("sdk_*agent.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Agent":
                continue
            if any(keyword.arg == "output_type" for keyword in node.keywords):
                violations.append(str(path.relative_to(ingestion_root)))

    assert violations == [], (
        "Source-grounded ingestion agents must finalize through an explicit tool so deterministic "
        "schema/provenance failures can be returned to the model for bounded repair. Native "
        f"output_type terminal agents bypass that repair loop: {violations}"
    )
