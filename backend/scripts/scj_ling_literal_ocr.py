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
import os
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
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
SHARD_COUNT = 20
RENDER_SCALE = 2.0
TARGET_CLASSIFICATIONS = frozenset({"misaligned", "no_native_text"})
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_GENERATION_URL = "https://openrouter.ai/api/v1/generation"

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
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _safe_model(value: str) -> str:
    return value.replace("/", "__").replace(":", "_")


def _list_objects(store: Any, prefix: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": store.config.bucket, "Prefix": prefix, "MaxKeys": 1000}
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


def _put_immutable(store: Any, *, key: str, payload: bytes, content_type: str, metadata: dict[str, str]) -> None:
    payload_sha = _sha256(payload)
    try:
        response = store.client.head_object(Bucket=store.config.bucket, Key=key)
    except Exception as exc:
        if not store.is_not_found(exc):
            raise
    else:
        existing = {str(k).lower(): str(v) for k, v in dict(response.get("Metadata") or {}).items()}
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
    successes = [item for item in _list_objects(store, CENSUS_PREFIX) if str(item.get("Key", "")).endswith("/_SUCCESS.json")]
    if not successes:
        raise RuntimeError("no completed SCJ Principales corpus-verification census found")
    latest = max(successes, key=lambda item: item.get("LastModified") or "")
    key = str(latest["Key"])
    payload = json.loads(_get_bytes(store, key))
    return key.rsplit("/", 1)[0], payload


def _extract_member(payload: bytes, member_name: str) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r:") as archive:
            member = archive.getmember(member_name)
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError(f"archive member has no payload: {member_name}")
            return stream.read()


def build_plan(*, output: Path) -> dict[str, Any]:
    store = build_s3_object_store()
    census_prefix, success = _latest_completed_census(store)
    inventory = json.loads(_get_bytes(store, f"{census_prefix}/inventory.json"))
    inventory_by_key = {str(item["object_key"]): item for item in inventory["documents"]}

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
        if selected:
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

    pages.sort(key=lambda x: (x["object_key"], x["page_index"]))
    for ordinal, item in enumerate(pages):
        item["ordinal"] = ordinal
        item["worker_index"] = int(item["page_index"]) % SHARD_COUNT

    counts = Counter(str(item["classification"]) for item in pages)
    plan_core = {
        "schema_version": 1,
        "census_prefix": census_prefix,
        "census_success": success,
        "model": MODEL,
        "provider": PROVIDER,
        "passes": PASSES,
        "shard_count": SHARD_COUNT,
        "render_scale": RENDER_SCALE,
        "target_classifications": sorted(TARGET_CLASSIFICATIONS),
        "documents": documents,
        "pages": pages,
    }
    plan_sha = _sha256(_canonical(plan_core))
    plan = {
        **plan_core,
        "plan_sha256": plan_sha,
        "counts": {"total_pages": len(pages), **dict(sorted(counts.items()))},
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


def _openrouter_json(*, method: str, url: str, api_key: str, body: dict[str, Any] | None = None, attempts: int = 5) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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


def _generation_metadata(*, generation_id: str, api_key: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"id": generation_id})
    # Metadata can lag the completion very briefly.
    for attempt in range(1, 6):
        try:
            response = _openrouter_json(
                method="GET",
                url=f"{OPENROUTER_GENERATION_URL}?{query}",
                api_key=api_key,
                attempts=1,
            )
            data = response.get("data")
            if isinstance(data, dict):
                return data
        except RuntimeError:
            if attempt == 5:
                raise
        time.sleep(attempt)
    raise RuntimeError(f"generation metadata unavailable: {generation_id}")


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
        "reasoning": {"effort": "none"},
        "provider": {
            "only": [PROVIDER_ROUTE],
            "order": [PROVIDER_ROUTE],
            "allow_fallbacks": False,
            "require_parameters": True,
        },
    }
    started = time.monotonic()
    response = _openrouter_json(method="POST", url=OPENROUTER_CHAT_URL, api_key=api_key, body=body)
    elapsed = time.monotonic() - started
    generation_id = str(response.get("id") or "")
    if not generation_id:
        raise RuntimeError("OpenRouter response omitted generation id")
    generation = _generation_metadata(generation_id=generation_id, api_key=api_key)
    returned_provider = str(generation.get("provider_name") or response.get("provider") or "")
    if returned_provider.casefold() != PROVIDER.casefold():
        raise RuntimeError(f"provider pin violated: expected {PROVIDER}, got {returned_provider or '<missing>'}")
    returned_model = str(generation.get("model") or response.get("model") or "")
    if "ling-3.0-flash-vl" not in returned_model.casefold():
        raise RuntimeError(f"model identity mismatch: {returned_model or '<missing>'}")
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
        "total_cost_usd": float(generation.get("total_cost") or generation.get("usage") or 0.0),
        "tokens_prompt": int(generation.get("tokens_prompt") or 0),
        "tokens_completion": int(generation.get("tokens_completion") or 0),
        "native_tokens_prompt": int(generation.get("native_tokens_prompt") or 0),
        "native_tokens_completion": int(generation.get("native_tokens_completion") or 0),
        "native_tokens_cached": int(generation.get("native_tokens_cached") or 0),
        "generation_time_ms": generation.get("generation_time"),
        "provider_metadata": {
            "is_byok": generation.get("is_byok"),
            "data_region": generation.get("data_region"),
            "upstream_inference_cost": generation.get("upstream_inference_cost"),
        },
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


def _source_pdf(store: Any, document: dict[str, Any]) -> bytes:
    response = store.client.get_object(Bucket=store.config.bucket, Key=document["object_key"])
    body = response["Body"].read()
    payload = body if isinstance(body, bytes) else bytes(body)
    actual_sha = _sha256(payload)
    if actual_sha != document["source_pdf_sha256"]:
        raise RuntimeError(
            f"source drift for {document['object_key']}: expected {document['source_pdf_sha256']}, got {actual_sha}"
        )
    return payload


def run_worker(
    *,
    plan_path: Path,
    worker_index: int,
    run_id: str,
    run_attempt: str,
    output: Path,
    max_pages: int = 0,
) -> dict[str, Any]:
    if not 0 <= worker_index < SHARD_COUNT:
        raise ValueError(f"worker_index must be 0..{SHARD_COUNT - 1}")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["model"] != MODEL or plan["provider"] != PROVIDER or int(plan["shard_count"]) != SHARD_COUNT:
        raise RuntimeError("plan/provider/model contract drift")
    plan_sha = str(plan["plan_sha256"])
    store = build_s3_object_store()
    docs = {str(doc["document_id"]): doc for doc in plan["documents"]}
    mine = [page for page in plan["pages"] if int(page["worker_index"]) == worker_index]
    if max_pages < 0:
        raise ValueError("max_pages must be zero or positive")
    if max_pages:
        mine = mine[:max_pages]
    output.mkdir(parents=True, exist_ok=True)

    charged = 0.0
    restored = 0
    completed = 0
    current_document_id: str | None = None
    current_pdf_bytes: bytes | None = None
    records: list[dict[str, Any]] = []

    for page in mine:
        document_id = str(page["document_id"])
        page_index = int(page["page_index"])
        key1 = _page_key(plan_sha, document_id, page_index, 1)
        key2 = _page_key(plan_sha, document_id, page_index, 2)
        existing2 = _load_json_if_exists(store, key2)
        if existing2 is not None:
            restored += 1
            records.append(existing2)
            continue

        if current_document_id != document_id or current_pdf_bytes is None:
            current_pdf_bytes = _source_pdf(store, docs[document_id])
            current_document_id = document_id
        image = _render_page(current_pdf_bytes, page_index)
        image_sha = _sha256(image)

        first = _load_json_if_exists(store, key1)
        if first is None:
            observation1 = _call_ling(image_png=image, prompt=PASS1_PROMPT, api_key=api_key)
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
                "transcription_sha256": _sha256(observation1["transcription"].encode("utf-8")),
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

        prompt2 = PASS2_PROMPT.format(prior=str(first["transcription"]))
        observation2 = _call_ling(image_png=image, prompt=prompt2, api_key=api_key)
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
            "transcription_sha256": _sha256(observation2["transcription"].encode("utf-8")),
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
        charged += float(second["total_cost_usd"])
        completed += 1
        records.append(second)
        print(
            json.dumps(
                {
                    "worker": worker_index,
                    "document_id": document_id,
                    "page_index": page_index,
                    "completed": completed,
                    "restored": restored,
                    "charged_this_worker_usd": round(charged, 8),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    summary = {
        "schema_version": 1,
        "worker_index": worker_index,
        "assigned_pages": len(mine),
        "newly_completed_pages": completed,
        "restored_pages": restored,
        "charged_this_run_usd": round(charged, 10),
        "model": MODEL,
        "provider": PROVIDER,
        "passes": PASSES,
        "plan_sha256": plan_sha,
    }
    (output / f"worker-{worker_index:02d}.json").write_bytes(_canonical(summary))
    return summary


def aggregate(*, plan_path: Path, worker_root: Path, run_id: str, run_attempt: str, output: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_sha = str(plan["plan_sha256"])
    store = build_s3_object_store()
    expected = {(str(page["document_id"]), int(page["page_index"])) for page in plan["pages"]}
    observed: set[tuple[str, int]] = set()
    cumulative_cost = 0.0
    pass1_cost = 0.0
    pass2_cost = 0.0
    returned_models: Counter[str] = Counter()
    returned_providers: Counter[str] = Counter()

    for document_id, page_index in sorted(expected):
        for pass_number in (1, 2):
            key = _page_key(plan_sha, document_id, page_index, pass_number)
            record = _load_json_if_exists(store, key)
            if record is None:
                raise RuntimeError(f"missing OCR evidence: {key}")
            if str(record.get("plan_sha256")) != plan_sha:
                raise RuntimeError(f"wrong plan identity: {key}")
            if str(record.get("returned_provider", "")).casefold() != PROVIDER.casefold():
                raise RuntimeError(f"wrong provider in evidence: {key}")
            cost = float(record.get("total_cost_usd") or 0.0)
            cumulative_cost += cost
            if pass_number == 1:
                pass1_cost += cost
            else:
                pass2_cost += cost
                observed.add((document_id, page_index))
            returned_models[str(record.get("returned_model") or "")] += 1
            returned_providers[str(record.get("returned_provider") or "")] += 1

    if observed != expected:
        raise RuntimeError("aggregate coverage does not exactly match frozen plan")

    worker_summaries = []
    for path in sorted(worker_root.rglob("worker-*.json")):
        worker_summaries.append(json.loads(path.read_text(encoding="utf-8")))
    if len(worker_summaries) != SHARD_COUNT:
        raise RuntimeError(f"expected {SHARD_COUNT} worker summaries, found {len(worker_summaries)}")
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
