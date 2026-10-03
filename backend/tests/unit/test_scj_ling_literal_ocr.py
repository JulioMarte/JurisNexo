from __future__ import annotations

import asyncio
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


def _patch_openrouter_json(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    fake_request: Callable[..., dict[str, object]],
) -> None:
    async def async_fake_request(**kwargs: object) -> tuple[dict[str, object], int]:
        return fake_request(**kwargs), 1

    monkeypatch.setattr(module, "_openrouter_json", async_fake_request)


def _call_ling(module: ModuleType, **kwargs: object) -> dict[str, Any]:
    return asyncio.run(
        module._call_ling(
            client=cast(Any, object()),
            request_gate=module.AsyncRequestGate(1),
            **kwargs,
        )
    )


def test_async_request_gate_caps_global_in_flight_calls() -> None:
    module = _module()
    gate = module.AsyncRequestGate(7)
    active = 0
    peak = 0

    class FakeClient:
        async def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> Any:
            nonlocal active, peak
            del headers, json
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1
            return module.httpx.Response(200, json={"ok": True})

    async def run_calls() -> None:
        client = FakeClient()
        await asyncio.gather(
            *(
                gate.post(
                    client,
                    url="https://example.invalid",
                    headers={},
                    body={},
                )
                for _ in range(31)
            )
        )

    asyncio.run(run_calls())

    assert peak == 7
    assert gate.peak_in_flight == 7
    assert gate.in_flight == 0


def test_async_openrouter_keeps_five_attempt_backoff_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    status_codes = [429, 502, 503, 504, 200]
    observed_delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        observed_delays.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)

    async def handler(request: Any) -> Any:
        status_code = status_codes.pop(0)
        return module.httpx.Response(
            status_code,
            json={"ok": status_code == 200},
            request=request,
        )

    async def run_request() -> tuple[dict[str, Any], int]:
        async with module.httpx.AsyncClient(
            transport=module.httpx.MockTransport(handler),
        ) as client:
            return await module._openrouter_json(
                client=client,
                request_gate=module.AsyncRequestGate(2),
                api_key="test-key",
                body={"model": module.MODEL},
            )

    response, attempts = asyncio.run(run_request())

    assert response == {"ok": True}
    assert attempts == 5
    assert observed_delays == [1, 2, 4, 8]


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

    _patch_openrouter_json(monkeypatch, module, fake_request)

    result = _call_ling(
        module,
        image_png=b"not-a-real-png-needed-for-request-contract",
        prompt=module.PASS1_PROMPT,
        api_key="test-key",
    )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == module.MODEL
    assert body["reasoning"] == {"effort": "none"}
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


def test_ling_accepts_empty_text_as_valid_literal_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-empty",
            "model": module.MODEL,
            "provider": "NovitaAI",
            "usage": {"cost": 0.0001},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": ""},
                }
            ],
        }

    _patch_openrouter_json(monkeypatch, module, fake_request)

    result = _call_ling(
        module,
        image_png=b"image",
        prompt=module.PASS1_PROMPT,
        api_key="test-key",
    )

    assert result["transcription"] == ""
    assert result["generation_id"] == "gen-empty"


def test_ling_accepts_null_stop_as_valid_empty_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-null-empty",
            "model": module.MODEL,
            "provider": "NovitaAI",
            "usage": {"cost": 0.0001},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": None},
                }
            ],
        }

    _patch_openrouter_json(monkeypatch, module, fake_request)

    result = _call_ling(
        module,
        image_png=b"image",
        prompt=module.PASS1_PROMPT,
        api_key="test-key",
    )

    assert result["transcription"] == ""


def test_ling_rejects_null_completion_without_success_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-null-invalid",
            "model": module.MODEL,
            "provider": "NovitaAI",
            "usage": {"cost": 0.0001},
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": None},
                }
            ],
        }

    _patch_openrouter_json(monkeypatch, module, fake_request)

    with pytest.raises(RuntimeError, match="no textual completion"):
        _call_ling(
            module,
            image_png=b"image",
            prompt=module.PASS1_PROMPT,
            api_key="test-key",
        )


def test_ling_rejects_http_200_choice_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_request(**_kwargs: object) -> dict[str, object]:
        return {
            "id": "gen-error",
            "model": module.MODEL,
            "provider": "NovitaAI",
            "usage": {"cost": 0.0},
            "choices": [
                {
                    "finish_reason": "error",
                    "error": {"message": "provider failed"},
                    "message": {"content": ""},
                }
            ],
        }

    _patch_openrouter_json(monkeypatch, module, fake_request)

    with pytest.raises(RuntimeError, match="OpenRouter completion failed"):
        _call_ling(
            module,
            image_png=b"image",
            prompt=module.PASS1_PROMPT,
            api_key="test-key",
        )


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

    _patch_openrouter_json(monkeypatch, module, fake_request)

    with pytest.raises(RuntimeError, match="provider pin violated"):
        _call_ling(
            module,
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

    _patch_openrouter_json(monkeypatch, module, fake_request)

    with pytest.raises(RuntimeError, match="usage.cost"):
        _call_ling(
            module,
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


def test_async_pass1_checkpoint_resumes_at_pass2_without_repeating_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    plan_sha = "b" * 64
    page = {
        "document_id": "doc",
        "object_key": "source.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": 7,
        "classification": "misaligned",
    }
    saved: dict[str, dict[str, Any]] = {}
    calls: list[str] = []
    writes: list[str] = []
    image_png = b"fixture-rendered-page"
    pixel_sha = "c" * 64
    profile_id = "pypdfium-test-profile"

    def fake_load(_store: object, key: str) -> dict[str, Any] | None:
        return saved.get(key)

    def fake_put(
        _store: object,
        *,
        key: str,
        payload: bytes,
        **_kwargs: object,
    ) -> None:
        saved[key] = json.loads(payload)
        writes.append(key)

    async def fake_run_blocking(
        _executor: object,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)

    def fake_render(_pdf_bytes: bytes, _page_index: int) -> bytes:
        return image_png

    async def fake_ling(**kwargs: object) -> dict[str, object]:
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        pass_number = len(calls)
        transcription = "literal pass one" if pass_number == 1 else "verified pass two"
        return {
            "transcription": transcription,
            "generation_id": f"generation-{pass_number}",
            "requested_model": module.MODEL,
            "returned_model": module.MODEL,
            "requested_provider": module.PROVIDER,
            "requested_provider_route": module.PROVIDER_ROUTE,
            "requested_reasoning_effort": "none",
            "returned_provider": "NovitaAI",
            "latency_seconds_client": 0.01,
            "retry_count": 0,
            "total_cost_usd": 0.001,
            "tokens_prompt": 10,
            "tokens_completion": 5,
            "tokens_total": 15,
            "reasoning_tokens": 0,
        }

    monkeypatch.setattr(module, "_load_json_if_exists", fake_load)
    monkeypatch.setattr(module, "_put_immutable", fake_put)
    monkeypatch.setattr(module, "_run_blocking", fake_run_blocking)
    monkeypatch.setattr(module, "_render_page", fake_render)
    monkeypatch.setattr(module, "_render_pixel_sha256", lambda _image: pixel_sha)
    monkeypatch.setattr(module, "_render_profile_id", lambda: profile_id)
    monkeypatch.setattr(module, "_call_ling", fake_ling)

    def process(phase: str) -> dict[str, Any]:
        return asyncio.run(
            module._process_page(
                store=object(),
                plan_sha=plan_sha,
                page=page,
                pdf_bytes=b"pdf",
                api_key="test-key",
                run_id="run",
                run_attempt="1",
                client=object(),
                request_gate=module.AsyncRequestGate(2),
                io_executor=object(),
                render_executor=object(),
                phase=phase,
            )
        )

    pass1 = process("pass1")
    assert pass1["completed"] == 1
    assert list(saved) == [module._page_key(plan_sha, "doc", 7, 1)]

    pass2 = process("pass2")
    assert pass2["completed"] == 1
    assert pass2["api_generations"] == 1
    assert writes == [
        module._page_key(plan_sha, "doc", 7, 1),
        module._page_key(plan_sha, "doc", 7, 2),
    ]
    assert len(calls) == 2
    assert calls[0] == module.PASS1_PROMPT
    assert "literal pass one" in calls[1]
    assert saved[module._page_key(plan_sha, "doc", 7, 2)][
        "prior_transcription_sha256"
    ] == saved[module._page_key(plan_sha, "doc", 7, 1)]["transcription_sha256"]

    restored = process("pass2")
    assert restored["restored"] == 1
    assert len(calls) == 2


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

    def fake_source(_store: object, document: dict[str, object]) -> bytes:
        events.append(("source", str(document["document_id"])))
        return str(document["document_id"]).encode()

    async def fake_process(**kwargs: object) -> dict[str, object]:
        page_value = kwargs["page"]
        assert isinstance(page_value, dict)
        page = cast(dict[str, object], page_value)
        page_index = page["page_index"]
        assert isinstance(page_index, int)
        events.append(
            ("process", (str(page["document_id"]), page_index))
        )
        return {
            "restored": 0,
            "completed": 1,
            "charged": 0.01,
            "api_generations": 2,
            "retry_count": 0,
            "api_latency_seconds": 0.2,
        }

    async def fake_run_blocking(
        _executor: object,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)

    monkeypatch.setenv("JURISNEXO_S3_BUCKET", "fixture-bucket")
    monkeypatch.setenv("JURISNEXO_S3_REGION", "us-east-1")
    monkeypatch.setattr(module, "build_s3_object_store", lambda **_kwargs: object())
    monkeypatch.setattr(module, "_run_blocking", fake_run_blocking)
    monkeypatch.setattr(module, "_source_pdf", fake_source)
    monkeypatch.setattr(module, "_process_page", fake_process)

    summary = module.run_worker(
        plan_path=plan_path,
        worker_index=0,
        run_id="123",
        run_attempt="1",
        output=tmp_path / "worker",
        max_pages=4,
        max_concurrent_requests=3,
    )

    assert [value for kind, value in events if kind == "source"] == [
        "doc-a",
        "doc-b",
    ]
    assert sorted(value for kind, value in events if kind == "process") == [
        ("doc-a", 0),
        ("doc-a", 1),
        ("doc-a", 2),
        ("doc-b", 0),
    ]
    assert summary["assigned_pages"] == 4
    assert summary["newly_completed_pages"] == 4
    assert summary["documents_processed"] == 2
    assert summary["charged_this_run_usd"] == pytest.approx(0.04)
    assert summary["max_concurrent_requests"] == 3
    assert summary["successful_generations"] == 8


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

    active_tasks = 0
    peak_tasks = 0
    active_lock = asyncio.Lock()

    def fake_store() -> object:
        return object()

    monkeypatch.setenv("JURISNEXO_S3_BUCKET", "fixture-bucket")
    monkeypatch.setenv("JURISNEXO_S3_REGION", "us-east-1")
    monkeypatch.setattr(module, "build_s3_object_store", lambda **_kwargs: fake_store())
    async def fake_run_blocking(
        _executor: object,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)

    monkeypatch.setattr(module, "_run_blocking", fake_run_blocking)
    def fake_source(
        _store: object,
        _document: dict[str, object],
    ) -> bytes:
        return b"pdf"

    monkeypatch.setattr(module, "_source_pdf", fake_source)

    async def fake_process(**_kwargs: object) -> dict[str, object]:
        nonlocal active_tasks, peak_tasks
        async with active_lock:
            active_tasks += 1
            peak_tasks = max(peak_tasks, active_tasks)
        await asyncio.sleep(0.005)
        async with active_lock:
            active_tasks -= 1
        return {
            "restored": 0,
            "completed": 1,
            "charged": 0.0,
            "api_generations": 2,
            "retry_count": 0,
            "api_latency_seconds": 0.0,
        }

    monkeypatch.setattr(module, "_process_page", fake_process)

    summary = module.run_worker(
        plan_path=plan_path,
        worker_index=0,
        run_id="123",
        run_attempt="2",
        output=tmp_path / "worker",
        max_concurrent_requests=7,
    )

    assert peak_tasks == 7
    assert summary["assigned_pages"] == 25
    assert summary["newly_completed_pages"] == 25
    assert summary["max_concurrent_requests"] == 7


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

    async def fake_process_for_drift(**_kwargs: object) -> dict[str, object]:
        return {
            "restored": 0,
            "completed": 0,
            "charged": 0.0,
            "api_generations": 0,
            "retry_count": 0,
            "api_latency_seconds": 0.0,
        }

    async def fake_run_blocking_for_drift(
        _executor: object,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)

    monkeypatch.setenv("JURISNEXO_S3_BUCKET", "fixture-bucket")
    monkeypatch.setenv("JURISNEXO_S3_REGION", "us-east-1")
    monkeypatch.setattr(module, "build_s3_object_store", lambda **_kwargs: fake_store_for_drift())
    monkeypatch.setattr(module, "_run_blocking", fake_run_blocking_for_drift)
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
