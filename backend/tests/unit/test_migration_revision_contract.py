import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def test_alembic_revision_ids_fit_version_table() -> None:
    failures: list[str] = []
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision: str | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            has_revision_target = any(
                isinstance(target, ast.Name) and target.id == "revision"
                for target in node.targets
            )
            if not has_revision_target:
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                revision = node.value.value
                break
        if revision is None:
            failures.append(f"{path.name}: missing literal revision id")
        elif len(revision) > 32:
            failures.append(f"{path.name}: revision id has {len(revision)} chars: {revision}")

    assert not failures, "\n".join(failures)
