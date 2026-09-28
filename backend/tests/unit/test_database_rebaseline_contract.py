from __future__ import annotations

import ast
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
VERSIONS = MIGRATIONS / "versions"
BASELINE = MIGRATIONS / "baseline.sql"


def _assignment(module: ast.Module, name: str) -> object | None:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        return ast.literal_eval(node.value)
    return None


def test_rebaseline_keeps_one_root_and_one_linear_head() -> None:
    revisions = sorted(
        path for path in VERSIONS.glob("*.py") if path.name != "__init__.py"
    )
    parsed: dict[str, str | None] = {}
    for path in revisions:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _assignment(tree, "revision")
        down_revision = _assignment(tree, "down_revision")
        assert isinstance(revision, str)
        assert down_revision is None or isinstance(down_revision, str)
        assert revision not in parsed
        parsed[revision] = down_revision

    roots = [revision for revision, parent in parsed.items() if parent is None]
    assert roots == ["baseline_20260919"]

    children: dict[str, list[str]] = {revision: [] for revision in parsed}
    for revision, parent in parsed.items():
        if parent is None:
            continue
        assert parent in parsed, f"{revision} references unknown parent {parent}"
        children[parent].append(revision)

    assert all(len(items) <= 1 for items in children.values())
    heads = [revision for revision, items in children.items() if not items]
    assert len(heads) == 1


def test_rebaseline_revision_is_new_root() -> None:
    path = VERSIONS / "0001_jurisnexo_baseline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert _assignment(tree, "revision") == "baseline_20260919"
    assert _assignment(tree, "down_revision") is None


def test_baseline_is_postgresql_only_and_substantial() -> None:
    text = BASELINE.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "supabase" not in lowered
    assert "auth." not in lowered
    assert "storage." not in lowered
    assert text.count("CREATE TABLE ") >= 170
    assert text.count("CREATE FUNCTION ") >= 30
    assert text.count("CREATE TRIGGER ") >= 25
    assert text.count("CREATE INDEX ") + text.count("CREATE UNIQUE INDEX ") >= 150
    assert text.count("INSERT INTO ") >= 500
    assert text.count("COMMENT ON ") >= 100


def test_dump_normalizer_preserves_uuid_relationship_topology(tmp_path: Path) -> None:
    from jurisnexo.db_dump_normalizer import normalize

    uuid_a = "11111111-1111-4111-8111-111111111111"
    uuid_b = "22222222-2222-4222-8222-222222222222"
    source = (
        f"INSERT INTO a VALUES ('{uuid_a}', '2026-09-20 01:02:03+00');\n"
        f"INSERT INTO b VALUES ('{uuid_b}', '{uuid_a}', '2026-09-20 04:05:06.123+00');\n"
    )
    normalized = normalize(source)

    assert normalized.count("<uuid:1>") == 2
    assert normalized.count("<uuid:2>") == 1
    assert normalized.count("<generated-timestamptz>") == 2
    assert uuid_a not in normalized
    assert uuid_b not in normalized
