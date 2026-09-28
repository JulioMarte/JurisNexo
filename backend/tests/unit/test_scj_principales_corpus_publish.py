from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = (
        REPO_ROOT
        / "backend"
        / "scripts"
        / "scj_principales_corpus_publish.py"
    )
    spec = importlib.util.spec_from_file_location(
        "scj_principales_corpus_publish",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deterministic_archive_is_byte_stable(tmp_path: Path) -> None:
    publish = _module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "document.json").write_text(
        '{"ok":true}\n',
        encoding="utf-8",
    )
    nested = source / "reference-text"
    nested.mkdir()
    (nested / "page-00000.txt").write_text(
        "texto\n",
        encoding="utf-8",
    )

    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    first_sha = publish.build_deterministic_archive(source, first)
    second_sha = publish.build_deterministic_archive(source, second)

    assert first_sha == second_sha
    assert first.read_bytes() == second.read_bytes()


def test_dataset_prefix_rejects_non_hex_identity() -> None:
    publish = _module()
    with pytest.raises(ValueError, match="inventory_sha256"):
        publish._dataset_prefix(
            inventory_sha256="not-a-sha",
            policy_sha256="b" * 64,
            code_revision="c" * 40,
        )


def test_dataset_prefix_is_content_addressed() -> None:
    publish = _module()
    prefix = publish._dataset_prefix(
        inventory_sha256="a" * 64,
        policy_sha256="b" * 64,
        code_revision="c" * 40,
    )

    assert prefix.endswith(
        f"/{'a' * 64}/{'b' * 64}/{'c' * 40}"
    )
