from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def test_summary_publish_requires_document_receipts(tmp_path: Path) -> None:
    publish = _module()
    inventory_sha = "a" * 64
    policy_sha = "b" * 64
    revision = "c" * 40
    source_sha = "d" * 64

    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        (
            '{"inventory_sha256":"'
            + inventory_sha
            + '","documents":[{"object_key":"a.pdf"}]}'
        ),
        encoding="utf-8",
    )
    summary = tmp_path / "census-summary.json"
    summary.write_text(
        (
            '{"inventory_sha256":"'
            + inventory_sha
            + '","documents":1,"total_pages":1,'
            + '"document_ranking":[{"object_key":"a.pdf",'
            + '"source_pdf_sha256":"'
            + source_sha
            + '","policy_sha256":"'
            + policy_sha
            + '"}]}'
        ),
        encoding="utf-8",
    )
    documents = tmp_path / "documents"
    documents.mkdir()

    with pytest.raises(RuntimeError, match="receipt count"):
        publish.publish_summary(
            summary_path=summary,
            inventory_path=inventory,
            documents_root=documents,
            code_revision=revision,
        )


def test_restore_document_verifies_archive_and_source_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = _module()
    inventory_sha = "a" * 64
    revision = "c" * 40
    document_id = "d" * 16
    object_key = "jurisdictions/do/scj/principales-sentencias/a.pdf"

    source = tmp_path / "source"
    source.mkdir()
    document = {
        "complete_scan": True,
        "interrupted": False,
        "policy_sha256": publish._policy_sha256(),
        "code_revision": revision,
        "source_pdf_sha256": "e" * 64,
        "object_key": object_key,
    }
    (source / "document.json").write_text(
        __import__("json").dumps(document),
        encoding="utf-8",
    )
    archive_path = tmp_path / "document.tar.gz"
    archive_sha = publish.build_deterministic_archive(
        source,
        archive_path,
    )
    payload = archive_path.read_bytes()

    class Body:
        def read(self) -> bytes:
            return payload

    class Client:
        def head_object(self, **_kwargs: object) -> dict[str, object]:
            return {
                "Metadata": {
                    "payload-sha256": archive_sha,
                }
            }

        def get_object(self, **_kwargs: object) -> dict[str, object]:
            return {"Body": Body()}

    store = SimpleNamespace(
        client=Client(),
        config=SimpleNamespace(bucket="bucket"),
        is_not_found=lambda _exc: False,
    )
    monkeypatch.setattr(
        publish,
        "build_s3_object_store",
        lambda: store,
    )

    output = tmp_path / "restored"
    receipt = publish.restore_document(
        output_dir=output,
        inventory_sha256=inventory_sha,
        document_id=document_id,
        code_revision=revision,
        object_key=object_key,
    )

    assert receipt is not None
    assert receipt["archive_sha256"] == archive_sha
    assert receipt["object_key"] == object_key
    assert (output / "document.json").is_file()
    assert (output / "publish.json").is_file()
