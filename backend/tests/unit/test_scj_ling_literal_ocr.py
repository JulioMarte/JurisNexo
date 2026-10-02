from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

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


def test_dynamic_scheduler_contract_uses_twenty_workers() -> None:
    module = _module()
    assert module.WORKER_COUNT == 20
    assert not hasattr(module, "SHARD_COUNT")


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
            "provider": "NovitaAI",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
                "cost": 0.00123,
            },
            "choices": [{"message": {"content": "texto literal"}}],
        }

    monkeypatch.setattr(module, "_openrouter_json", fake_request)

    result = module._call_ling(
        image_png=b"not-a-real-png-needed-for-request-contract",
        prompt=module.PASS1_PROMPT,
        api_key="test-key",
    )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == module.MODEL
    assert "reasoning" not in body
    assert body["usage"] == {"include": True}
    assert body["provider"] == {
        "only": [module.PROVIDER_ROUTE],
        "order": [module.PROVIDER_ROUTE],
        "allow_fallbacks": False,
        "require_parameters": True,
    }
    assert module.PROVIDER_ROUTE == "novita"
    assert module._openrouter_headers("secret") == {
        "Authorization": "Bearer secret",
        "Content-Type": "application/json",
        "X-OpenRouter-Cache": "true",
        "X-OpenRouter-Cache-TTL": "86400",
    }
    assert result["returned_provider"] == "NovitaAI"
    assert result["total_cost_usd"] == pytest.approx(0.00123)
    assert result["tokens_total"] == 125


def test_ling_rejects_provider_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-test",
            "model": module.MODEL,
            "provider": "DeepInfra",
            "usage": {"cost": 0.001},
            "choices": [{"message": {"content": "texto"}}],
        }

    monkeypatch.setattr(module, "_openrouter_json", fake_request)

    with pytest.raises(RuntimeError, match="provider pin violated"):
        module._call_ling(
            image_png=b"image",
            prompt=module.PASS1_PROMPT,
            api_key="test-key",
        )


def test_ling_refuses_unmetered_success(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-test",
            "model": module.MODEL,
            "provider": "NovitaAI",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "choices": [{"message": {"content": "texto"}}],
        }

    monkeypatch.setattr(module, "_openrouter_json", fake_request)

    with pytest.raises(RuntimeError, match="usage.cost"):
        module._call_ling(
            image_png=b"image",
            prompt=module.PASS1_PROMPT,
            api_key="test-key",
        )


def test_provider_identity_accepts_only_novita_names() -> None:
    module = _module()

    assert module._is_expected_provider("Novita")
    assert module._is_expected_provider("NovitaAI")
    assert module._is_expected_provider("novita")
    assert not module._is_expected_provider("DeepInfra")
    assert not module._is_expected_provider("")


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
    with (
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
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
    monkeypatch.setattr(module, "EXPECTED_DOCUMENTS", 1)
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

    def fake_store() -> object:
        return object()

    monkeypatch.setattr(module, "build_s3_object_store", fake_store)
    def fake_latest(_store: object) -> tuple[str, dict[str, object]]:
        return "census/generation", {"status": "complete"}

    def fake_list(_store: object, prefix: str) -> list[dict[str, object]]:
        if prefix.endswith("/documents/"):
            return [{"Key": "census/generation/documents/example.tar.gz"}]
        return []

    monkeypatch.setattr(module, "_latest_completed_census", fake_latest)
    monkeypatch.setattr(module, "_list_objects", fake_list)

    def fake_get(_store: object, key: str) -> bytes:
        if key.endswith("/inventory.json"):
            return json.dumps(inventory).encode()
        if key.endswith(".tar.gz"):
            return archive
        raise AssertionError(key)

    monkeypatch.setattr(module, "_get_bytes", fake_get)

    plan = module.build_plan(output=tmp_path)

    assert plan["counts"] == {"misaligned": 1, "total_documents": 1, "total_pages": 1}
    assert plan["pages"][0]["document_id"] == "0123456789abcdef"
    assert plan["documents"][0]["document_id"] == "0123456789abcdef"


def test_plan_rejects_incomplete_scj_decision_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    inventory: dict[str, Any] = {"documents": []}
    monkeypatch.setattr(module, "build_s3_object_store", lambda: object())

    def fake_latest(_store: object) -> tuple[str, dict[str, object]]:
        return "census/generation", {"status": "complete"}

    def fake_get(_store: object, key: str) -> bytes:
        if key.endswith("/inventory.json"):
            return json.dumps(inventory).encode()
        return b""

    monkeypatch.setattr(module, "_latest_completed_census", fake_latest)
    monkeypatch.setattr(module, "_get_bytes", fake_get)

    with pytest.raises(RuntimeError, match="must contain 36 documents"):
        module.build_plan(output=tmp_path)


def test_verify_plan_rejects_tampered_page_selection() -> None:
    module = _module()
    core: dict[str, Any] = {
        "schema_version": 1,
        "model": module.MODEL,
        "provider": module.PROVIDER,
        "worker_count": module.WORKER_COUNT,
        "pages": [
            {
                "document_id": "doc",
                "object_key": "source.pdf",
                "source_pdf_sha256": "a" * 64,
                "page_index": 1,
                "classification": "misaligned",
            }
        ],
    }
    page = core["pages"][0]
    assert isinstance(page, dict)
    plan = {
        **core,
        "plan_sha256": module._sha256(module._canonical(core)),
        "counts": {"total_pages": 1, "misaligned": 1},
    }
    page["page_index"] = 2

    with pytest.raises(RuntimeError, match="plan identity mismatch"):
        module._verify_plan(plan)


def test_verify_evidence_rejects_wrong_page_or_transcription_hash() -> None:
    module = _module()
    page = {
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
    }
    record = {
        "pass": 1,
        "plan_sha256": "b" * 64,
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 8,
        "requested_model": module.MODEL,
        "returned_model": module.MODEL,
        "requested_provider": module.PROVIDER,
        "requested_provider_route": module.PROVIDER_ROUTE,
        "returned_provider": "NovitaAI",
        "generation_id": "gen-test",
        "total_cost_usd": 0.001,
        "transcription": "texto",
        "transcription_sha256": module._sha256(b"texto"),
        "render_png_sha256": "c" * 64,
    }

    with pytest.raises(RuntimeError, match="page_index"):
        module._verify_evidence(
            record,
            plan_sha="b" * 64,
            page=page,
            pass_number=1,
            render_png_sha256="c" * 64,
        )

    record["page_index"] = 7
    record["transcription_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="transcription hash mismatch"):
        module._verify_evidence(
            record,
            plan_sha="b" * 64,
            page=page,
            pass_number=1,
            render_png_sha256="c" * 64,
        )


def test_verify_evidence_accepts_byte_different_render_for_same_source_page() -> None:
    module = _module()
    page = {
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
    }
    record = {
        "pass": 1,
        "plan_sha256": "b" * 64,
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
        "requested_model": module.MODEL,
        "returned_model": module.MODEL,
        "requested_provider": module.PROVIDER,
        "requested_provider_route": module.PROVIDER_ROUTE,
        "returned_provider": "NovitaAI",
        "generation_id": "gen-test",
        "total_cost_usd": 0.001,
        "transcription": "texto",
        "transcription_sha256": module._sha256(b"texto"),
        "render_png_sha256": "c" * 64,
    }

    module._verify_evidence(
        record,
        plan_sha="b" * 64,
        page=page,
        pass_number=1,
        render_png_sha256="d" * 64,
    )


def test_verify_evidence_rejects_invalid_cost() -> None:
    module = _module()
    page = {
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
    }
    record = {
        "pass": 1,
        "plan_sha256": "b" * 64,
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
        "requested_model": module.MODEL,
        "returned_model": module.MODEL,
        "requested_provider": module.PROVIDER,
        "requested_provider_route": module.PROVIDER_ROUTE,
        "returned_provider": "NovitaAI",
        "generation_id": "gen-test",
        "total_cost_usd": -0.01,
        "transcription": "texto",
        "transcription_sha256": module._sha256(b"texto"),
        "render_png_sha256": "c" * 64,
    }

    with pytest.raises(RuntimeError, match="cost must be finite and non-negative"):
        module._verify_evidence(
            record,
            plan_sha="b" * 64,
            page=page,
            pass_number=1,
            render_png_sha256="c" * 64,
        )


def _scheduler_plan(module: ModuleType) -> dict[str, Any]:
    documents = [
        {
            "document_id": "doc-a",
            "object_key": "a.pdf",
            "source_pdf_sha256": "a" * 64,
            "page_indexes": [0, 1, 2],
        },
        {
            "document_id": "doc-b",
            "object_key": "b.pdf",
            "source_pdf_sha256": "b" * 64,
            "page_indexes": [0, 1],
        },
    ]
    pages = [
        {
            "document_id": document_id,
            "object_key": object_key,
            "source_pdf_sha256": source_sha,
            "page_index": page_index,
            "classification": "misaligned",
            "ordinal": ordinal,
        }
        for ordinal, (document_id, object_key, source_sha, page_index) in enumerate(
            [
                ("doc-a", "a.pdf", "a" * 64, 0),
                ("doc-a", "a.pdf", "a" * 64, 1),
                ("doc-a", "a.pdf", "a" * 64, 2),
                ("doc-b", "b.pdf", "b" * 64, 0),
                ("doc-b", "b.pdf", "b" * 64, 1),
            ]
        )
    ]
    core: dict[str, Any] = {
        "schema_version": 1,
        "model": module.MODEL,
        "provider": module.PROVIDER,
        "passes": module.PASSES,
        "worker_count": module.WORKER_COUNT,
        "documents": documents,
        "pages": pages,
    }
    return {
        **core,
        "plan_sha256": module._sha256(module._canonical(core)),
        "counts": {
            "total_documents": 2,
            "total_pages": 5,
            "misaligned": 5,
        },
    }


def test_verify_plan_accepts_document_count_contract() -> None:
    module = _module()
    plan = _scheduler_plan(module)

    assert module._verify_plan(plan) == plan["plan_sha256"]


def test_dynamic_scheduler_enforces_global_canary_and_pdf_barrier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    plan = _scheduler_plan(module)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(module._canonical(plan))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    events: list[tuple[str, object]] = []

    class FakeFuture:
        def __init__(self, result: dict[str, object]) -> None:
            self._result = result

        def result(self) -> dict[str, object]:
            return self._result

    class FakePool:
        def __init__(self, *, max_workers: int, thread_name_prefix: str) -> None:
            events.append(("pool", (max_workers, thread_name_prefix)))

        def __enter__(self) -> FakePool:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def submit(
            self,
            function: Callable[..., dict[str, object]],
            **kwargs: object,
        ) -> FakeFuture:
            page_value = kwargs["page"]
            assert isinstance(page_value, dict)
            page = cast(dict[str, object], page_value)
            page_index = page["page_index"]
            assert isinstance(page_index, int)
            events.append(
                ("submit", (str(page["document_id"]), page_index))
            )
            result = function(**kwargs)
            return FakeFuture(result)

    def fake_as_completed(futures: list[FakeFuture]) -> list[FakeFuture]:
        events.append(("barrier", len(futures)))
        return futures

    def fake_source(_store: object, document: dict[str, object]) -> bytes:
        events.append(("source", str(document["document_id"])))
        return str(document["document_id"]).encode()

    def fake_process(**kwargs: object) -> dict[str, object]:
        page_value = kwargs["page"]
        assert isinstance(page_value, dict)
        page = cast(dict[str, object], page_value)
        page_index = page["page_index"]
        assert isinstance(page_index, int)
        events.append(
            ("process", (str(page["document_id"]), page_index))
        )
        return {"restored": 0, "completed": 1, "charged": 0.01}

    monkeypatch.setattr(module, "build_s3_object_store", lambda: object())
    monkeypatch.setattr(module, "ThreadPoolExecutor", FakePool)
    monkeypatch.setattr(module, "as_completed", fake_as_completed)
    monkeypatch.setattr(module, "_source_pdf", fake_source)
    monkeypatch.setattr(module, "_process_page", fake_process)

    summary = module.run_worker(
        plan_path=plan_path,
        worker_index=0,
        run_id="123",
        run_attempt="1",
        output=tmp_path / "worker",
        max_pages=4,
    )

    assert events[0] == ("pool", (20, "ling"))
    assert [value for kind, value in events if kind == "source"] == [
        "doc-a",
        "doc-b",
    ]
    assert [value for kind, value in events if kind == "barrier"] == [3, 1]
    assert [value for kind, value in events if kind == "submit"] == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-a", 2),
        ("doc-b", 0),
    ]
    assert summary["assigned_pages"] == 4
    assert summary["newly_completed_pages"] == 4
    assert summary["documents_processed"] == 2
    assert summary["charged_this_run_usd"] == pytest.approx(0.04)


def test_dynamic_scheduler_bounds_each_pdf_batch_to_worker_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    plan = _scheduler_plan(module)
    prototype = dict(plan["pages"][0])
    plan["pages"] = [
        {
            **prototype,
            "page_index": index,
            "ordinal": index,
        }
        for index in range(25)
    ]
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "counts"}
    }
    plan["plan_sha256"] = module._sha256(module._canonical(core))
    plan["counts"] = {
        "total_documents": 2,
        "total_pages": 25,
        "misaligned": 25,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(module._canonical(plan))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    batch_sizes: list[int] = []

    class FakeFuture:
        def result(self) -> dict[str, object]:
            return {"restored": 0, "completed": 1, "charged": 0.0}

    class FakePool:
        def __init__(self, *, max_workers: int, thread_name_prefix: str) -> None:
            assert max_workers == 20
            assert thread_name_prefix == "ling"

        def __enter__(self) -> FakePool:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def submit(
            self,
            _function: Callable[..., dict[str, object]],
            **_kwargs: object,
        ) -> FakeFuture:
            return FakeFuture()

    def fake_as_completed(futures: list[FakeFuture]) -> list[FakeFuture]:
        batch_sizes.append(len(futures))
        return futures

    def fake_store() -> object:
        return object()

    monkeypatch.setattr(module, "build_s3_object_store", fake_store)
    monkeypatch.setattr(module, "ThreadPoolExecutor", FakePool)
    monkeypatch.setattr(module, "as_completed", fake_as_completed)
    def fake_source(
        _store: object,
        _document: dict[str, object],
    ) -> bytes:
        return b"pdf"

    monkeypatch.setattr(module, "_source_pdf", fake_source)

    summary = module.run_worker(
        plan_path=plan_path,
        worker_index=0,
        run_id="123",
        run_attempt="2",
        output=tmp_path / "worker",
    )

    assert batch_sizes == [20, 5]
    assert summary["assigned_pages"] == 25
    assert summary["newly_completed_pages"] == 25


def test_dynamic_scheduler_rejects_accounting_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    plan = _scheduler_plan(module)
    plan["pages"] = plan["pages"][:1]
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "counts"}
    }
    plan["plan_sha256"] = module._sha256(module._canonical(core))
    plan["counts"] = {
        "total_documents": 2,
        "total_pages": 1,
        "misaligned": 1,
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(module._canonical(plan))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def fake_store_for_drift() -> object:
        return object()

    def fake_source_for_drift(
        _store: object,
        _document: dict[str, object],
    ) -> bytes:
        return b"pdf"

    def fake_process_for_drift(**_kwargs: object) -> dict[str, object]:
        return {"restored": 0, "completed": 0, "charged": 0.0}

    monkeypatch.setattr(module, "build_s3_object_store", fake_store_for_drift)
    monkeypatch.setattr(module, "_source_pdf", fake_source_for_drift)
    monkeypatch.setattr(module, "_process_page", fake_process_for_drift)

    with pytest.raises(RuntimeError, match="scheduler accounting mismatch"):
        module.run_worker(
            plan_path=plan_path,
            worker_index=0,
            run_id="123",
            run_attempt="1",
            output=tmp_path / "worker",
        )
