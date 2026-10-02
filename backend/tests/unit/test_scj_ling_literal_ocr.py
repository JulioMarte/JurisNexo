from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_ling_literal_ocr.py"
    spec = importlib.util.spec_from_file_location("scj_ling_literal_ocr", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_page_ownership_is_pdf_local_and_deterministic() -> None:
    module = _module()
    pages = [{"page_index": index} for index in range(61)]
    for page in pages:
        page["worker_index"] = int(page["page_index"]) % module.SHARD_COUNT

    owners = {
        index: [
            int(page["page_index"])
            for page in pages
            if int(page["worker_index"]) == index
        ]
        for index in range(module.SHARD_COUNT)
    }

    flattened = [page for group in owners.values() for page in group]
    assert sorted(flattened) == list(range(61))
    assert len(flattened) == len(set(flattened))
    assert all(
        page_index % module.SHARD_COUNT == worker
        for worker, group in owners.items()
        for page_index in group
    )


def test_second_pass_is_adversarial_but_image_authoritative() -> None:
    module = _module()
    prompt = module.PASS2_PROMPT.format(prior="SCJ-SS-22-191")

    assert "image is the authority" in prompt.lower()
    assert "fallible candidate" in prompt.lower()
    assert "SCJ-SS-22-191" in prompt
    assert "do not paraphrase" in prompt.lower()


def test_ling_request_is_hard_pinned_to_novita(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    seen: dict[str, object] = {}

    def fake_request(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "id": "gen-test",
            "model": module.MODEL,
            "choices": [{"message": {"content": "texto literal"}}],
        }

    def fake_generation(**_kwargs: object) -> dict[str, object]:
        return {
            "provider_name": module.PROVIDER,
            "model": module.MODEL,
            "total_cost": 0.00123,
            "tokens_prompt": 100,
            "tokens_completion": 25,
        }

    monkeypatch.setattr(module, "_openrouter_json", fake_request)
    monkeypatch.setattr(module, "_generation_metadata", fake_generation)

    result = module._call_ling(
        image_png=b"not-a-real-png-needed-for-request-contract",
        prompt=module.PASS1_PROMPT,
        api_key="test-key",
    )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == module.MODEL
    assert body["reasoning"] == {"effort": "none"}
    assert body["provider"] == {
        "only": [module.PROVIDER_ROUTE],
        "order": [module.PROVIDER_ROUTE],
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    assert module.PROVIDER_ROUTE == "novita"
    assert result["returned_provider"] == "NovitaAI"
    assert result["total_cost_usd"] == pytest.approx(0.00123)


def test_ling_rejects_provider_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-test",
            "model": module.MODEL,
            "choices": [{"message": {"content": "texto"}}],
        }

    def fake_generation(**_kwargs: object) -> dict[str, object]:
        return {
            "provider_name": "DeepInfra",
            "model": module.MODEL,
            "total_cost": 0.001,
        }

    monkeypatch.setattr(module, "_openrouter_json", fake_request)
    monkeypatch.setattr(module, "_generation_metadata", fake_generation)

    with pytest.raises(RuntimeError, match="provider pin violated"):
        module._call_ling(
            image_png=b"image",
            prompt=module.PASS1_PROMPT,
            api_key="test-key",
        )


def test_output_key_separates_passes_and_model_provider() -> None:
    module = _module()
    one = module._page_key("a" * 64, "doc123", 7, 1)
    two = module._page_key("a" * 64, "doc123", 7, 2)

    assert one != two
    assert "inclusionai__ling-3.0-flash-vl" in one
    assert "/NovitaAI/" in one
    assert one.endswith("/pass-1.json")
    assert two.endswith("/pass-2.json")


def _census_archive() -> bytes:
    document = {
        "object_key": "jurisdictions/do/scj/principales-sentencias/example.pdf",
        "source_pdf_sha256": "b" * 64,
        "source_page_count": 2,
    }
    pages = [
        {
            "object_key": document["object_key"],
            "source_pdf_sha256": document["source_pdf_sha256"],
            "page_index": 0,
            "classification": "misaligned",
            "native_text_sha256": "c" * 64,
            "ocr_text_sha256": "d" * 64,
        },
        {
            "object_key": document["object_key"],
            "source_pdf_sha256": document["source_pdf_sha256"],
            "page_index": 1,
            "classification": "aligned",
        },
    ]
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, payload in {
                "document.json": json.dumps(document).encode(),
                "pages.jsonl": (
                    "".join(json.dumps(page) + "\n" for page in pages).encode()
                ),
            }.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    return raw.getvalue()


def test_plan_uses_frozen_inventory_document_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    object_key = "jurisdictions/do/scj/principales-sentencias/example.pdf"
    inventory = {
        "documents": [
            {
                "object_key": object_key,
                "document_id": "0123456789abcdef",
                "size_bytes": 123,
                "etag": "etag",
            }
        ]
    }
    archive = _census_archive()

    monkeypatch.setattr(module, "build_s3_object_store", lambda: object())
    monkeypatch.setattr(
        module,
        "_latest_completed_census",
        lambda _store: ("census/generation", {"status": "complete"}),
    )
    monkeypatch.setattr(
        module,
        "_list_objects",
        lambda _store, prefix: (
            [{"Key": "census/generation/documents/example.tar.gz"}]
            if prefix.endswith("/documents/")
            else []
        ),
    )

    def fake_get(_store: object, key: str) -> bytes:
        if key.endswith("/inventory.json"):
            return json.dumps(inventory).encode()
        if key.endswith(".tar.gz"):
            return archive
        raise AssertionError(key)

    monkeypatch.setattr(module, "_get_bytes", fake_get)

    plan = module.build_plan(output=tmp_path)

    assert plan["counts"] == {"misaligned": 1, "total_pages": 1}
    assert plan["pages"][0]["document_id"] == "0123456789abcdef"
    assert plan["documents"][0]["document_id"] == "0123456789abcdef"
