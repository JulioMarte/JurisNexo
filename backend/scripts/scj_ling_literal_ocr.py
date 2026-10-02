"""Two-pass literal OCR for unresolved SCJ Principales pages using Ling VL via OpenRouter.

The durable corpus census is the independent selector. This job never treats a
model transcription as primary-source truth: every result is bound to the
immutable PDF SHA, rendered-page SHA, model, provider, pass number and exact
OpenRouter generation/cost metadata.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import math
import os
import tarfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store

CENSUS_PREFIX = "benchmarks/scj-principales/corpus-verification/v1/"
OUTPUT_PREFIX = "benchmarks/scj-principales/ling-literal-ocr/v1"
MODEL = "inclusionai/ling-3.0-flash-vl"
PROVIDER = "NovitaAI"
PROVIDER_ROUTE = "novita"
PASSES = 2
WORKER_COUNT = 20
EXPECTED_DOCUMENTS = 36
RENDER_SCALE = 2.0
TARGET_CLASSIFICATIONS = frozenset({"misaligned", "no_native_text"})
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_CACHE_TTL_SECONDS = "86400"

PASS1_PROMPT = """Transcribe this judicial-document page literally.
Return only the visible text, in reading order, with no Markdown fence, summary,
explanation, correction, modernization, or invented content. Preserve spelling,
capitalization, punctuation, numbers, case identifiers, accents, headings and
line/paragraph breaks as faithfully as the image permits. If a character is
truly illegible, use [ilegible] only for that smallest unreadable fragment."""

PASS2_PROMPT = """You are performing an adversarial fidelity pass over a prior OCR.
The image is the authority. The prior OCR below is only a fallible candidate.
Inspect the image independently, challenge every character, number, accent,
punctuation mark, name, case identifier, heading and line break, and correct any
difference you can actually see. Do not paraphrase, summarize, explain or infer
missing legal content. Return only the most literal transcription supported by
the image.

PRIOR OCR:
---BEGIN PRIOR OCR---
{prior}
---END PRIOR OCR---"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (serialized + "\n").encode("utf-8")


def _safe_model(value: str) -> str:
    return value.replace("/", "__").replace(":", "_")


def _is_expected_provider(value: object) -> bool:
    return PROVIDER_ROUTE in str(value or "").casefold()


def _list_objects(store: Any, prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        out.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            return out
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing omitted continuation token")


def _get_bytes(store: Any, key: str) -> bytes:
    response = store.client.get_object(Bucket=store.config.bucket, Key=key)
    body = response["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _exists(store: Any, key: str) -> bool:
    try:
        store.client.head_object(Bucket=store.config.bucket, Key=key)
    except Exception as exc:
        if store.is_not_found(exc):
            return False
        raise
    return True


def _put_immutable(
    store: Any,
    *,
    key: str,
    payload: bytes,
    content_type: str,
    metadata: dict[str, str],
) -> None:
    payload_sha = _sha256(payload)
    try:
        response = store.client.head_object(Bucket=store.config.bucket, Key=key)
    except Exception as exc:
        if not store.is_not_found(exc):
            raise
    else:
        existing = {
            str(k).lower(): str(v)
            for k, v in dict(response.get("Metadata") or {}).items()
        }
        if existing.get("payload-sha256") != payload_sha:
            raise RuntimeError(f"immutable OCR evidence differs at {key}")
        return
    store.put(
        key=key,
        content=payload,
        content_type=content_type,
        metadata={**metadata, "payload-sha256": payload_sha},
    )


def _latest_completed_census(store: Any) -> tuple[str, dict[str, Any]]:
    successes = [
        item
        for item in _list_objects(store, CENSUS_PREFIX)
        if str(item.get("Key", "")).endswith("/_SUCCESS.json")
    ]
    if not successes:
        raise RuntimeError("no completed SCJ Principales corpus-verification census found")
    latest = max(successes, key=lambda item: item.get("LastModified") or "")
    key = str(latest["Key"])
    payload = json.loads(_get_bytes(store, key))
    return key.rsplit("/", 1)[0], payload


def _extract_member(payload: bytes, member_name: str) -> bytes:
    with (
        gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed,
        tarfile.open(fileobj=compressed, mode="r:") as archive,
    ):
        member = archive.getmember(member_name)
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(f"archive member has no payload: {member_name}")
        return stream.read()


def build_plan(*, output: Path) -> dict[str, Any]:
    store = build_s3_object_store()
    census_prefix, success = _latest_completed_census(store)
    inventory = json.loads(_get_bytes(store, f"{census_prefix}/inventory.json"))
    inventory_documents = inventory["documents"]
    if len(inventory_documents) != EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"frozen census inventory must contain {EXPECTED_DOCUMENTS} documents; "
            f"found {len(inventory_documents)}"
        )
    inventory_by_key = {str(item["object_key"]): item for item in inventory_documents}

    pages: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    document_objects = [
        item for item in _list_objects(store, f"{census_prefix}/documents/")
        if str(item.get("Key", "")).endswith(".tar.gz")
    ]
    for obj in sorted(document_objects, key=lambda item: str(item["Key"])):
        archive = _get_bytes(store, str(obj["Key"]))
        document = json.loads(_extract_member(archive, "document.json"))
        object_key = str(document["object_key"])
        frozen = inventory_by_key.get(object_key)
        if frozen is None:
            raise RuntimeError(f"document absent from frozen inventory: {object_key}")
        document_id = str(frozen["document_id"])
        source_sha = str(document["source_pdf_sha256"])
        selected: list[int] = []
        lines = _extract_member(archive, "pages.jsonl").decode("utf-8").splitlines()
        for line in lines:
            record = json.loads(line)
            if str(record.get("classification")) not in TARGET_CLASSIFICATIONS:
                continue
            page_index = int(record["page_index"])
            selected.append(page_index)
            pages.append(
                {
                    "document_id": document_id,
                    "object_key": object_key,
                    "source_pdf_sha256": source_sha,
                    "page_index": page_index,
                    "classification": record["classification"],
                    "native_text_sha256": record.get("native_text_sha256"),
                    "tesseract_text_sha256": record.get("ocr_text_sha256"),
                }
            )
        documents.append(
            {
                "document_id": document_id,
                "object_key": object_key,
                "source_pdf_sha256": source_sha,
                "expected_size": int(frozen.get("size_bytes") or frozen.get("size") or 0),
                "expected_etag": str(frozen.get("etag") or ""),
                "page_indexes": selected,
            }
        )

    if len(document_objects) != EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"completed census must publish {EXPECTED_DOCUMENTS} document archives; "
            f"found {len(document_objects)}"
        )
    if len(documents) != EXPECTED_DOCUMENTS:
        raise RuntimeError(
            f"Ling recovery plan must describe all {EXPECTED_DOCUMENTS} documents; "
            f"found {len(documents)}"
        )

    pages.sort(key=lambda x: (x["object_key"], x["page_index"]))
    for ordinal, item in enumerate(pages):
        item["ordinal"] = ordinal

    counts = Counter(str(item["classification"]) for item in pages)
    plan_core = {
        "schema_version": 1,
        "census_prefix": census_prefix,
        "census_success": success,
        "model": MODEL,
        "provider": PROVIDER,
        "passes": PASSES,
        "worker_count": WORKER_COUNT,
        "render_scale": RENDER_SCALE,
        "target_classifications": sorted(TARGET_CLASSIFICATIONS),
        "documents": documents,
        "pages": pages,
    }
    plan_sha = _sha256(_canonical(plan_core))
    plan = {
        **plan_core,
        "plan_sha256": plan_sha,
        "counts": {
            "total_documents": len(documents),
            "total_pages": len(pages),
            **dict(sorted(counts.items())),
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.json").write_bytes(_canonical(plan))
    print(json.dumps(plan["counts"], indent=2, sort_keys=True))
    return plan


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        page = doc[page_index]
        try:
            bitmap = page.render(scale=RENDER_SCALE)
            try:
                image = bitmap.to_pil()
                stream = io.BytesIO()
                image.save(stream, format="PNG")
                return stream.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        doc.close()


def _openrouter_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Cache": "true",
        "X-OpenRouter-Cache-TTL": OPENROUTER_CACHE_TTL_SECONDS,
    }


def _openrouter_json(
    *,
    method: str,
    url: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    attempts: int = 5,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=_openrouter_headers(api_key),
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {408, 409, 429, 500, 502, 503, 504} or attempt == attempts:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt == attempts:
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc
        time.sleep(min(2 ** (attempt - 1), 20))
    assert last is not None
    raise last


def _content_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(item.get("text") or "") for item in content if isinstance(item, dict)]
        text = "".join(parts).strip()
        if text:
            return text
    raise RuntimeError("OpenRouter response has no textual completion")


def _call_ling(*, image_png: bytes, prompt: str, api_key: str) -> dict[str, Any]:
    image_url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 16384,
        "usage": {"include": True},
        "provider": {
            "only": [PROVIDER_ROUTE],
            "order": [PROVIDER_ROUTE],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
    }
    started = time.monotonic()
    response = _openrouter_json(
        method="POST",
        url=OPENROUTER_CHAT_URL,
        api_key=api_key,
        body=body,
    )
    elapsed = time.monotonic() - started
    generation_id = str(response.get("id") or "")
    if not generation_id:
        raise RuntimeError("OpenRouter response omitted generation id")

    returned_provider = str(response.get("provider") or "")
    if not _is_expected_provider(returned_provider):
        raise RuntimeError(
            f"provider pin violated: expected {PROVIDER}, "
            f"got {returned_provider or '<missing>'}"
        )
    returned_model = str(response.get("model") or "")
    if "ling-3.0-flash-vl" not in returned_model.casefold():
        raise RuntimeError(f"model identity mismatch: {returned_model or '<missing>'}")

    usage_raw = response.get("usage")
    if not isinstance(usage_raw, dict):
        raise RuntimeError("OpenRouter response omitted usage accounting")
    usage = {str(key): value for key, value in usage_raw.items()}
    raw_cost = usage.get("cost")
    if (
        isinstance(raw_cost, bool)
        or not isinstance(raw_cost, (int, float))
        or not math.isfinite(float(raw_cost))
        or float(raw_cost) < 0
    ):
        raise RuntimeError("OpenRouter response omitted valid exact usage.cost")

    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    details = usage.get("completion_tokens_details")
    reasoning_tokens = (
        details.get("reasoning_tokens")
        if isinstance(details, dict)
        else None
    )
    return {
        "transcription": _content_text(response),
        "generation_id": generation_id,
        "requested_model": MODEL,
        "returned_model": returned_model,
        "requested_provider": PROVIDER,
        "requested_provider_route": PROVIDER_ROUTE,
        "requested_reasoning_effort": "none",
        "returned_provider": returned_provider,
        "latency_seconds_client": round(elapsed, 6),
        "total_cost_usd": float(raw_cost),
        "tokens_prompt": int(prompt_tokens) if isinstance(prompt_tokens, int) else 0,
        "tokens_completion": (
            int(completion_tokens) if isinstance(completion_tokens, int) else 0
        ),
        "tokens_total": int(total_tokens) if isinstance(total_tokens, int) else 0,
        "reasoning_tokens": (
            int(reasoning_tokens) if isinstance(reasoning_tokens, int) else 0
        ),
    }


def _page_key(plan_sha: str, document_id: str, page_index: int, pass_number: int) -> str:
    return (
        f"{OUTPUT_PREFIX}/{plan_sha}/{_safe_model(MODEL)}/{PROVIDER}/"
        f"pages/{document_id}/{page_index:06d}/pass-{pass_number}.json"
    )


def _load_json_if_exists(store: Any, key: str) -> dict[str, Any] | None:
    if not _exists(store, key):
        return None
    return json.loads(_get_bytes(store, key))


def _verify_plan(plan: dict[str, Any]) -> str:
    claimed = str(plan.get("plan_sha256") or "")
    core = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_sha256", "counts"}
    }
    actual = _sha256(_canonical(core))
    if claimed != actual:
        raise RuntimeError(
            f"plan identity mismatch: claimed {claimed or '<missing>'}, got {actual}"
        )
    pages = plan.get("pages")
    if not isinstance(pages, list):
        raise RuntimeError("plan pages must be a list")
    expected_counts = Counter(str(item["classification"]) for item in pages)
    documents = plan.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("plan documents must be a list")
    expected = {
        "total_documents": len(documents),
        "total_pages": len(pages),
        **dict(sorted(expected_counts.items())),
    }
    if plan.get("counts") != expected:
        raise RuntimeError("plan counts do not match plan pages")
    return claimed


def _verify_evidence(
    record: dict[str, Any],
    *,
    plan_sha: str,
    page: dict[str, Any],
    pass_number: int,
    render_png_sha256: str | None = None,
    prior_key: str | None = None,
    prior_sha256: str | None = None,
) -> None:
    expected = {
        "plan_sha256": plan_sha,
        "document_id": str(page["document_id"]),
        "object_key": str(page["object_key"]),
        "source_pdf_sha256": str(page["source_pdf_sha256"]),
        "page_index": int(page["page_index"]),
        "pass": pass_number,
        "requested_model": MODEL,
        "requested_provider": PROVIDER,
        "requested_provider_route": PROVIDER_ROUTE,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise RuntimeError(
                f"OCR evidence identity mismatch for {field}: "
                f"expected {value!r}, got {record.get(field)!r}"
            )
    if not _is_expected_provider(record.get("returned_provider")):
        raise RuntimeError("OCR evidence provider pin violated")
    if "ling-3.0-flash-vl" not in str(record.get("returned_model") or "").casefold():
        raise RuntimeError("OCR evidence model identity mismatch")
    transcription = record.get("transcription")
    if not isinstance(transcription, str):
        raise RuntimeError("OCR evidence transcription is missing")
    if record.get("transcription_sha256") != _sha256(transcription.encode("utf-8")):
        raise RuntimeError("OCR evidence transcription hash mismatch")
    if render_png_sha256 is not None and record.get("render_png_sha256") != render_png_sha256:
        raise RuntimeError("OCR evidence render hash mismatch")
    generation_id = record.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id.strip():
        raise RuntimeError("OCR evidence generation id is missing")
    raw_cost = record.get("total_cost_usd")
    if (
        isinstance(raw_cost, bool)
        or not isinstance(raw_cost, (int, float))
        or not math.isfinite(float(raw_cost))
        or float(raw_cost) < 0
    ):
        raise RuntimeError("OCR evidence cost must be finite and non-negative")
    if pass_number == 2:
        if record.get("prior_pass_key") != prior_key:
            raise RuntimeError("OCR pass-2 prior object identity mismatch")
        if record.get("prior_transcription_sha256") != prior_sha256:
            raise RuntimeError("OCR pass-2 prior transcription hash mismatch")


def _source_pdf(store: Any, document: dict[str, Any]) -> bytes:
    response = store.client.get_object(Bucket=store.config.bucket, Key=document["object_key"])
    body = response["Body"].read()
    payload = body if isinstance(body, bytes) else bytes(body)
    actual_sha = _sha256(payload)
    if actual_sha != document["source_pdf_sha256"]:
        raise RuntimeError(
            f"source drift for {document['object_key']}: "
            f"expected {document['source_pdf_sha256']}, got {actual_sha}"
        )
    return payload


def _process_page(
    *,
    store: Any,
    plan_sha: str,
    page: dict[str, Any],
    pdf_bytes: bytes,
    api_key: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    document_id = str(page["document_id"])
    page_index = int(page["page_index"])
    key1 = _page_key(plan_sha, document_id, page_index, 1)
    key2 = _page_key(plan_sha, document_id, page_index, 2)
    image = _render_page(pdf_bytes, page_index)
    image_sha = _sha256(image)

    first = _load_json_if_exists(store, key1)
    if first is not None:
        _verify_evidence(
            first,
            plan_sha=plan_sha,
            page=page,
            pass_number=1,
            render_png_sha256=image_sha,
        )

    second = _load_json_if_exists(store, key2)
    if second is not None:
        if first is None:
            raise RuntimeError(f"pass 2 exists without pass 1: {key2}")
        _verify_evidence(
            second,
            plan_sha=plan_sha,
            page=page,
            pass_number=2,
            render_png_sha256=image_sha,
            prior_key=key1,
            prior_sha256=str(first["transcription_sha256"]),
        )
        return {"restored": 1, "completed": 0, "charged": 0.0}

    charged = 0.0
    if first is None:
        observation1 = _call_ling(
            image_png=image,
            prompt=PASS1_PROMPT,
            api_key=api_key,
        )
        first = {
            "schema_version": 1,
            "pass": 1,
            "plan_sha256": plan_sha,
            "document_id": document_id,
            "object_key": page["object_key"],
            "source_pdf_sha256": page["source_pdf_sha256"],
            "page_index": page_index,
            "source_classification": page["classification"],
            "render_png_sha256": image_sha,
            "native_text_sha256": page.get("native_text_sha256"),
            "tesseract_text_sha256": page.get("tesseract_text_sha256"),
            "github_run_id": run_id,
            "github_run_attempt": run_attempt,
            **observation1,
            "transcription_sha256": _sha256(
                observation1["transcription"].encode("utf-8")
            ),
        }
        _put_immutable(
            store,
            key=key1,
            payload=_canonical(first),
            content_type="application/json",
            metadata={
                "plan-sha256": plan_sha,
                "source-pdf-sha256": str(page["source_pdf_sha256"]),
                "render-png-sha256": image_sha,
                "model": _safe_model(MODEL),
                "provider": PROVIDER,
                "pass": "1",
            },
        )
        charged += float(first["total_cost_usd"])

    observation2 = _call_ling(
        image_png=image,
        prompt=PASS2_PROMPT.format(prior=str(first["transcription"])),
        api_key=api_key,
    )
    second = {
        "schema_version": 1,
        "pass": 2,
        "plan_sha256": plan_sha,
        "document_id": document_id,
        "object_key": page["object_key"],
        "source_pdf_sha256": page["source_pdf_sha256"],
        "page_index": page_index,
        "source_classification": page["classification"],
        "render_png_sha256": image_sha,
        "prior_pass_key": key1,
        "prior_transcription_sha256": first["transcription_sha256"],
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
        **observation2,
        "transcription_sha256": _sha256(
            observation2["transcription"].encode("utf-8")
        ),
    }
    _put_immutable(
        store,
        key=key2,
        payload=_canonical(second),
        content_type="application/json",
        metadata={
            "plan-sha256": plan_sha,
            "source-pdf-sha256": str(page["source_pdf_sha256"]),
            "render-png-sha256": image_sha,
            "model": _safe_model(MODEL),
            "provider": PROVIDER,
            "pass": "2",
        },
    )
    return {
        "restored": 0,
        "completed": 1,
        "charged": charged + float(second["total_cost_usd"]),
    }


def run_worker(
    *,
    plan_path: Path,
    worker_index: int,
    run_id: str,
    run_attempt: str,
    output: Path,
    max_pages: int = 0,
) -> dict[str, Any]:
    if worker_index != 0:
        raise ValueError("dynamic pool coordinator must use worker_index 0")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    if max_pages < 0:
        raise ValueError("max_pages must be zero or positive")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_sha = _verify_plan(plan)
    if (
        plan["model"] != MODEL
        or plan["provider"] != PROVIDER
        or int(plan["worker_count"]) != WORKER_COUNT
    ):
        raise RuntimeError("plan/provider/model/worker contract drift")

    store = build_s3_object_store()
    documents = {
        str(document["document_id"]): document
        for document in plan["documents"]
    }
    pages_by_document: dict[str, list[dict[str, Any]]] = {}
    for page in plan["pages"]:
        pages_by_document.setdefault(str(page["document_id"]), []).append(page)

    remaining = max_pages
    charged = 0.0
    restored = 0
    completed = 0
    assigned = 0
    documents_processed = 0
    output.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(
        max_workers=WORKER_COUNT,
        thread_name_prefix="ling",
    ) as pool:
        for document in plan["documents"]:
            document_id = str(document["document_id"])
            document_pages = list(pages_by_document.get(document_id, []))
            if max_pages:
                if remaining <= 0:
                    break
                document_pages = document_pages[:remaining]
                remaining -= len(document_pages)
            if not document_pages:
                continue

            pdf_bytes = _source_pdf(store, documents[document_id])
            futures = [
                pool.submit(
                    _process_page,
                    store=store,
                    plan_sha=plan_sha,
                    page=page,
                    pdf_bytes=pdf_bytes,
                    api_key=api_key,
                    run_id=run_id,
                    run_attempt=run_attempt,
                )
                for page in document_pages
            ]
            assigned += len(futures)

            # This barrier is intentional: all selected pages from the current
            # PDF finish before the next source PDF is opened.
            for future in as_completed(futures):
                result = future.result()
                charged += float(result["charged"])
                restored += int(result["restored"])
                completed += int(result["completed"])
                print(
                    json.dumps(
                        {
                            "document_id": document_id,
                            "completed": completed,
                            "restored": restored,
                            "charged_this_run_usd": round(charged, 8),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            documents_processed += 1

    if assigned != completed + restored:
        raise RuntimeError("dynamic scheduler accounting mismatch")

    summary = {
        "schema_version": 2,
        "scheduler": "pdf-serial-dynamic-page-pool",
        "worker_index": 0,
        "worker_count": WORKER_COUNT,
        "documents_processed": documents_processed,
        "assigned_pages": assigned,
        "newly_completed_pages": completed,
        "restored_pages": restored,
        "charged_this_run_usd": round(charged, 10),
        "model": MODEL,
        "provider": PROVIDER,
        "passes": PASSES,
        "plan_sha256": plan_sha,
    }
    (output / "worker-00.json").write_bytes(_canonical(summary))
    return summary

def aggregate(
    *,
    plan_path: Path,
    worker_root: Path,
    run_id: str,
    run_attempt: str,
    output: Path,
) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_sha = _verify_plan(plan)
    store = build_s3_object_store()
    expected = {(str(page["document_id"]), int(page["page_index"])) for page in plan["pages"]}
    observed: set[tuple[str, int]] = set()
    cumulative_cost = 0.0
    pass1_cost = 0.0
    pass2_cost = 0.0
    returned_models: Counter[str] = Counter()
    returned_providers: Counter[str] = Counter()

    pages_by_identity = {
        (str(page["document_id"]), int(page["page_index"])): page
        for page in plan["pages"]
    }
    for document_id, page_index in sorted(expected):
        page = pages_by_identity[(document_id, page_index)]
        key1 = _page_key(plan_sha, document_id, page_index, 1)
        key2 = _page_key(plan_sha, document_id, page_index, 2)
        first = _load_json_if_exists(store, key1)
        second = _load_json_if_exists(store, key2)
        if first is None:
            raise RuntimeError(f"missing OCR evidence: {key1}")
        if second is None:
            raise RuntimeError(f"missing OCR evidence: {key2}")
        _verify_evidence(first, plan_sha=plan_sha, page=page, pass_number=1)
        _verify_evidence(
            second,
            plan_sha=plan_sha,
            page=page,
            pass_number=2,
            render_png_sha256=str(first["render_png_sha256"]),
            prior_key=key1,
            prior_sha256=str(first["transcription_sha256"]),
        )
        if second.get("render_png_sha256") != first.get("render_png_sha256"):
            raise RuntimeError(f"OCR pass render mismatch: {key2}")
        for pass_number, record in ((1, first), (2, second)):
            cost = float(record["total_cost_usd"])
            cumulative_cost += cost
            if pass_number == 1:
                pass1_cost += cost
            else:
                pass2_cost += cost
                observed.add((document_id, page_index))
            returned_models[str(record["returned_model"])] += 1
            returned_providers[str(record["returned_provider"])] += 1

    if observed != expected:
        raise RuntimeError("aggregate coverage does not exactly match frozen plan")

    worker_summaries = []
    for path in sorted(worker_root.rglob("worker-*.json")):
        worker_summaries.append(json.loads(path.read_text(encoding="utf-8")))
    if len(worker_summaries) != 1:
        raise RuntimeError(
            "expected one dynamic-pool summary, "
            f"found {len(worker_summaries)}"
        )
    for item in worker_summaries:
        if (
            item.get("plan_sha256") != plan_sha
            or item.get("model") != MODEL
            or item.get("provider") != PROVIDER
            or int(item.get("passes", 0)) != PASSES
            or int(item.get("worker_count", 0)) != WORKER_COUNT
        ):
            raise RuntimeError("worker summary contract drift")
        raw_charged = item.get("charged_this_run_usd")
        if (
            isinstance(raw_charged, bool)
            or not isinstance(raw_charged, (int, float))
            or not math.isfinite(float(raw_charged))
            or float(raw_charged) < 0
        ):
            raise RuntimeError("worker summary cost must be finite and non-negative")
    billed_this_run = sum(float(item["charged_this_run_usd"]) for item in worker_summaries)

    summary = {
        "schema_version": 1,
        "status": "complete",
        "plan_sha256": plan_sha,
        "census_prefix": plan["census_prefix"],
        "pages_completed": len(observed),
        "passes_per_page": PASSES,
        "api_generations": len(observed) * PASSES,
        "requested_model": MODEL,
        "requested_provider": PROVIDER,
        "returned_models": dict(sorted(returned_models.items())),
        "returned_providers": dict(sorted(returned_providers.items())),
        "cost_usd": {
            "billed_this_github_run": round(billed_this_run, 10),
            "cumulative_generation_total": round(cumulative_cost, 10),
            "pass_1_total": round(pass1_cost, 10),
            "pass_2_total": round(pass2_cost, 10),
        },
        "github_run_id": run_id,
        "github_run_attempt": run_attempt,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_bytes(_canonical(summary))
    stable_success = {
        "schema_version": 1,
        "status": "complete",
        "plan_sha256": plan_sha,
        "census_prefix": plan["census_prefix"],
        "pages_completed": len(observed),
        "passes_per_page": PASSES,
        "api_generations": len(observed) * PASSES,
        "requested_model": MODEL,
        "requested_provider": PROVIDER,
        "returned_models": dict(sorted(returned_models.items())),
        "returned_providers": dict(sorted(returned_providers.items())),
        "cumulative_generation_cost_usd": round(cumulative_cost, 10),
        "pass_1_cost_usd": round(pass1_cost, 10),
        "pass_2_cost_usd": round(pass2_cost, 10),
    }
    base = f"{OUTPUT_PREFIX}/{plan_sha}/{_safe_model(MODEL)}/{PROVIDER}"
    _put_immutable(
        store,
        key=f"{base}/_SUCCESS.json",
        payload=_canonical(stable_success),
        content_type="application/json",
        metadata={"plan-sha256": plan_sha, "model": _safe_model(MODEL), "provider": PROVIDER},
    )
    _put_immutable(
        store,
        key=f"{base}/runs/github-{run_id}-attempt-{run_attempt}/summary.json",
        payload=_canonical(summary),
        content_type="application/json",
        metadata={"plan-sha256": plan_sha, "model": _safe_model(MODEL), "provider": PROVIDER},
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--output", type=Path, required=True)

    worker = sub.add_parser("worker")
    worker.add_argument("--plan", type=Path, required=True)
    worker.add_argument("--worker-index", type=int, required=True)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--run-attempt", required=True)
    worker.add_argument("--output", type=Path, required=True)
    worker.add_argument("--max-pages", type=int, default=0)

    collect = sub.add_parser("aggregate")
    collect.add_argument("--plan", type=Path, required=True)
    collect.add_argument("--worker-root", type=Path, required=True)
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--run-attempt", required=True)
    collect.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "plan":
        build_plan(output=args.output)
    elif args.command == "worker":
        run_worker(
            plan_path=args.plan,
            worker_index=args.worker_index,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            output=args.output,
            max_pages=args.max_pages,
        )
    else:
        aggregate(
            plan_path=args.plan,
            worker_root=args.worker_root,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            output=args.output,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
