from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_single_pdf_quality_publish.py"
    spec = importlib.util.spec_from_file_location("scj_single_pdf_quality_publish", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NotFoundError(RuntimeError):
    not_found = True


class _Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        del Bucket
        if Key not in self.objects:
            raise _NotFoundError("not found")
        _, metadata = self.objects[Key]
        return {"Metadata": metadata}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> None:
        del Bucket, ContentType
        self.objects[Key] = (bytes(Body), dict(Metadata))


def _store() -> SimpleNamespace:
    client = _Client()
    return SimpleNamespace(
        client=client,
        config=SimpleNamespace(bucket="bucket"),
        is_not_found=lambda exc: bool(getattr(exc, "not_found", False)),
        put=lambda **kwargs: client.put_object(
            Bucket="bucket",
            Key=kwargs["key"],
            Body=kwargs["content"],
            ContentType=kwargs["content_type"],
            Metadata=kwargs["metadata"],
        ),
    )


def test_publish_stage_is_immutable_and_records_page_evidence(tmp_path: Path) -> None:
    module = _module()
    source_sha = "a" * 64
    revision = "b" * 40
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "object_key": "jurisdictions/do/scj/principales-sentencias/test.pdf",
                "source_pdf_sha256": source_sha,
            }
        ),
        encoding="utf-8",
    )
    input_dir = tmp_path / "quality"
    input_dir.mkdir()
    (input_dir / "pages.jsonl").write_text(
        json.dumps(
            {
                "page_index": 7,
                "ocr_engine": "tesseract",
                "ocr_engine_version": "5.5.0",
                "quality_route": "jev_review",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (input_dir / "summary.json").write_text(
        json.dumps({"total_pages": 1}) + "\n",
        encoding="utf-8",
    )
    store = _store()

    first = module.publish_stage(
        source_json=source,
        input_dir=input_dir,
        stage="deterministic",
        code_revision=revision,
        run_id="123",
        run_attempt="1",
        store=store,
    )
    second = module.publish_stage(
        source_json=source,
        input_dir=input_dir,
        stage="deterministic",
        code_revision=revision,
        run_id="123",
        run_attempt="1",
        store=store,
    )

    assert first == second
    assert first["file_count"] == 2
    prefix = str(first["prefix"])
    pages_key = f"{prefix}/pages.jsonl"
    manifest_key = str(first["manifest_key"])
    assert pages_key in store.client.objects
    assert manifest_key in store.client.objects
    payload, metadata = store.client.objects[pages_key]
    assert metadata["source-pdf-sha256"] == source_sha
    assert metadata["payload-sha256"] == hashlib.sha256(payload).hexdigest()


def test_publish_stage_rejects_mutation_at_same_identity(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps({"source_pdf_sha256": "c" * 64, "object_key": "x.pdf"}),
        encoding="utf-8",
    )
    input_dir = tmp_path / "jev"
    input_dir.mkdir()
    target = input_dir / "jev-decisions.jsonl"
    target.write_text('{"page_index":1}\n', encoding="utf-8")
    store = _store()

    module.publish_stage(
        source_json=source,
        input_dir=input_dir,
        stage="jev",
        code_revision="d" * 40,
        run_id="456",
        run_attempt="1",
        store=store,
    )
    target.write_text('{"page_index":2}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="immutable targeted evidence differs"):
        module.publish_stage(
            source_json=source,
            input_dir=input_dir,
            stage="jev",
            code_revision="d" * 40,
            run_id="456",
            run_attempt="1",
            store=store,
        )
