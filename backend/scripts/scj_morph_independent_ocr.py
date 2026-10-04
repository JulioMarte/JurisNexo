"""Independent OCR of adjudication pages (DeepSeek V4.1 Flash via a pinned provider).

Selects pages from the frozen Ling evidence (legal-span disagreements, changed
pages, or all), renders each source page exactly as the Ling worker did, and asks
a different provider/model with no candidate text to transcribe only what is
visible. Evidence is written locally as JSONL and optionally published per page.

This is independent evidence, not ground truth and not a canonical write.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image

from jurisnexo.acquisition.local_object_store import LocalObjectStore
from jurisnexo.acquisition.object_store import StoredObject
from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.independent_ocr import (
    INDEPENDENT_OCR_PROMPT,
    OcrTarget,
    build_record,
    shard_targets,
)
from jurisnexo.normalization.ling_literal_ocr_analysis import (
    CHANGE_EXACT,
    classify_change,
    legal_span_disagreements,
)

DEFAULT_PLAN_SHA = "63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4"
DEFAULT_LING_MODEL = "inclusionai/ling-3.0-flash-vl"
DEFAULT_LING_PROVIDER = "NovitaAI"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DEFAULT_PROVIDER_TAG = "morph/fp8"
LING_PREFIX = "benchmarks/scj-principales/ling-literal-ocr/v1"
LOCAL_OBJECT_ROOT_ENV = "JURISNEXO_LOCAL_OBJECT_ROOT"
LOCAL_CORPUS_ROOT_ENV = "JURISNEXO_LOCAL_CORPUS_ROOT"
RENDER_SCALE = 2.0
PASS_KEY = re.compile(r"^pass-(\d+)\.json$")
RENDER_LOCK = threading.Lock()


def _local_object_root() -> Path | None:
    for env_name in (LOCAL_OBJECT_ROOT_ENV, LOCAL_CORPUS_ROOT_ENV):
        value = os.environ.get(env_name, "").strip()
        if value:
            return Path(value)
    return None


def _build_store(object_root: Path | None) -> Any:
    root = object_root or _local_object_root()
    if root is not None:
        return LocalObjectStore(root)
    return build_s3_object_store()


def _render_pixel_sha256(image_png: bytes) -> str:
    import hashlib

    with Image.open(io.BytesIO(image_png)) as image:
        normalized = image.convert("RGBA")
        header = f"{normalized.width}x{normalized.height}:RGBA\0".encode()
        return hashlib.sha256(header + normalized.tobytes()).hexdigest()


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    with RENDER_LOCK:
        document = pdfium.PdfDocument(pdf_bytes)
        try:
            page = document[page_index]
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
            document.close()


def _load_ling_pages(
    store: Any,
    *,
    plan_sha: str,
    ling_model: str,
    ling_provider: str,
) -> dict[tuple[str, int], dict[int, dict[str, Any]]]:
    prefix = f"{LING_PREFIX}/{plan_sha}/{ling_model.replace('/', '__')}/{ling_provider}/pages/"
    grouped: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for stored in store.list_objects(prefix):
        if not isinstance(stored, StoredObject):
            continue
        match = PASS_KEY.match(stored.key.rsplit("/", 1)[-1])
        if match is None:
            continue
        parts = stored.key[len(prefix) :].split("/")
        if len(parts) != 3:
            continue
        payload = json.loads(store.get_bytes(stored.key))
        grouped.setdefault((parts[0], int(parts[1])), {})[int(match.group(1))] = payload
    return grouped


def _select_targets(
    grouped: dict[tuple[str, int], dict[int, dict[str, Any]]],
    *,
    selection: str,
) -> list[OcrTarget]:
    targets: list[OcrTarget] = []
    for (document_id, page_index), passes in sorted(grouped.items()):
        if 1 not in passes or 2 not in passes:
            continue
        first = str(passes[1].get("transcription") or "")
        second = str(passes[2].get("transcription") or "")
        if selection == "legal-disagreements":
            if not legal_span_disagreements(first, second):
                continue
        elif selection == "changed":
            if classify_change(first, second) == CHANGE_EXACT:
                continue
        elif selection != "all":
            raise ValueError("selection must be legal-disagreements, changed or all")
        first_record = passes[1]
        targets.append(
            OcrTarget(
                document_id=document_id,
                page_index=page_index,
                object_key=str(first_record["object_key"]),
                source_pdf_sha256=str(first_record["source_pdf_sha256"]),
            )
        )
    return targets


def _existing_keys(output: Path) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if not output.exists():
        return keys
    for line in output.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            keys.add((str(row["document_id"]), int(row["page_index"])))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--object-root", "--corpus-root", dest="object_root", type=Path, default=None
    )
    parser.add_argument("--plan-sha", default=DEFAULT_PLAN_SHA)
    parser.add_argument("--ling-model", default=DEFAULT_LING_MODEL)
    parser.add_argument("--ling-provider", default=DEFAULT_LING_PROVIDER)
    parser.add_argument(
        "--select",
        choices=("legal-disagreements", "changed", "all"),
        default="legal-disagreements",
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider-tag", default=DEFAULT_PROVIDER_TAG)
    parser.add_argument("--reasoning-effort", choices=("none", "high", "xhigh"), default="none")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    store = _build_store(args.object_root)
    grouped = _load_ling_pages(
        store,
        plan_sha=args.plan_sha,
        ling_model=args.ling_model,
        ling_provider=args.ling_provider,
    )
    targets = _select_targets(grouped, selection=args.select)
    targets = shard_targets(targets, shard_index=args.shard_index, shard_count=args.shard_count)
    if args.limit:
        targets = targets[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = _existing_keys(args.output)
    provider = OpenRouterVisualModelProvider(
        api_key=api_key,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        structured_mode="raw_text",
        provider_order=(args.provider_tag,),
        allow_provider_fallbacks=False,
        timeout_seconds=300.0,
    )

    pdf_cache: dict[str, bytes] = {}
    total_cost = 0.0
    written = 0
    failures = 0
    with args.output.open("a", encoding="utf-8") as sink:
        for target in targets:
            if (target.document_id, target.page_index) in done:
                continue
            if total_cost >= args.max_cost_usd:
                print(f"cost cap reached at {total_cost:.6f} USD")
                break
            if target.object_key not in pdf_cache:
                pdf_bytes = store.get_bytes(target.object_key)
                import hashlib

                actual = hashlib.sha256(pdf_bytes).hexdigest()
                if actual != target.source_pdf_sha256:
                    raise RuntimeError(
                        f"source drift for {target.object_key}: "
                        f"{actual} != {target.source_pdf_sha256}"
                    )
                pdf_cache[target.object_key] = pdf_bytes
            image = _render_page(pdf_cache[target.object_key], target.page_index)
            pixel_sha = _render_pixel_sha256(image)
            try:
                result = provider.verify_image_text(
                    image=image,
                    media_type="image/png",
                    prompt=INDEPENDENT_OCR_PROMPT,
                    json_schema={},
                    max_output_tokens=args.max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - per-page failure is recorded
                failures += 1
                print(f"FAILED {target.document_id}/{target.page_index}: {exc!r}")
                continue
            transcription = str(result.value.get("transcription") or "")
            record = build_record(
                target=target,
                render_pixel_sha256=pixel_sha,
                requested_model=args.model,
                provider_tag=args.provider_tag,
                returned_model=result.model,
                returned_provider=str(result.provider_metadata.get("routed_provider") or ""),
                reasoning_effort=args.reasoning_effort,
                transcription=transcription,
                prompt_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                cost_usd=result.cost_usd,
                response_id=result.response_id,
            )
            sink.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            sink.flush()
            written += 1
            total_cost += result.cost_usd or 0.0
            if written % 10 == 0:
                print(
                    f"progress written={written} cost={total_cost:.6f} "
                    f"model={result.model} provider={record.returned_provider}"
                )

    summary = {
        "selection": args.select,
        "plan_sha256": args.plan_sha,
        "model": args.model,
        "provider_tag": args.provider_tag,
        "reasoning_effort": args.reasoning_effort,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "targets": len(targets),
        "written": written,
        "failures": failures,
        "cost_usd": round(total_cost, 10),
    }
    (args.output.parent / "independent-ocr-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
