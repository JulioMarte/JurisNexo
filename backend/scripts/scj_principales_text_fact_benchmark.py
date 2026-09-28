from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider
from jurisnexo.normalization.legal_fact_benchmark import (
    FACT_FIELDS,
    extract_reference_facts,
    score_legal_facts,
)

from scj_principales_visual_corpus_benchmark import _download, _native_text

MANIFEST = Path(os.environ.get("SCJ_TEXT_FACT_MANIFEST", "scj-visual-corpus-manifest.json"))
OUTPUT = Path(os.environ.get("SCJ_TEXT_FACT_OUTPUT", "scj-text-fact-output"))
MODEL = os.environ["JURISNEXO_OPENROUTER_TEXT_MODEL"]
PROVIDER = os.environ.get("SCJ_TEXT_FACT_PROVIDER", "")
REASONING = os.environ.get("SCJ_TEXT_FACT_REASONING", "high")
PAGE_COUNT = int(os.environ.get("SCJ_TEXT_FACT_PAGE_COUNT", "10"))
MAX_CONCURRENCY = int(os.environ.get("SCJ_TEXT_FACT_MAX_CONCURRENCY", "5"))

PROMPT_PREFIX = """Extract only legal facts explicitly present in the supplied Dominican judgment page.
Do not infer, normalize, repair, summarize, or invent values. Preserve each value as written in the text.
Return every occurrence, including duplicates. If a category has no explicit value, return an empty array.

PAGE TEXT:
"""


def _schema() -> dict[str, Any]:
    properties = {field: {"type": "array", "items": {"type": "string"}} for field in FACT_FIELDS}
    return {
        "type": "object",
        "properties": properties,
        "required": list(FACT_FIELDS),
        "additionalProperties": False,
    }


def _provider() -> OpenRouterStructuredModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return OpenRouterStructuredModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=MODEL,
        base_url=settings.base_url,
        timeout_seconds=120.0,
        structured_mode="json_schema",
        provider_order=(PROVIDER,) if PROVIDER else (),
        allow_provider_fallbacks=not bool(PROVIDER),
        max_structured_attempts=2,
    )


def _load_texts(samples: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    store = build_s3_object_store()
    loaded: list[tuple[dict[str, Any], str]] = []
    cached_key = ""
    source = b""
    for sample in samples:
        key = str(sample["object_key"])
        if key != cached_key:
            source = _download(store, key)
            cached_key = key
        text = _native_text(source, int(sample["page_index"]))
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != sample["reference_sha256"]:
            raise RuntimeError(f"reference drift: {sample['sample_id']}")
        loaded.append((sample, text))
    return loaded


def _run(item: tuple[dict[str, Any], str]) -> dict[str, Any]:
    sample, text = item
    started = time.perf_counter()
    expected = extract_reference_facts(text)
    try:
        result = _provider().generate_structured(
            prompt=PROMPT_PREFIX + text,
            json_schema=_schema(),
            max_output_tokens=4096,
            thinking_level=REASONING,
        )
        predicted = {
            field: tuple(str(value) for value in result.value[field])
            for field in FACT_FIELDS
        }
        score = score_legal_facts(expected=expected, predicted=predicted)
        return {
            "sample_id": sample["sample_id"],
            "object_key": sample["object_key"],
            "page_index": sample["page_index"],
            "reference_sha256": sample["reference_sha256"],
            "model": result.model,
            "routed_provider": str((result.provider_metadata or {}).get("routed_provider") or ""),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "thinking_tokens": result.usage.thinking_tokens,
            "total_tokens": result.usage.total_tokens,
            "cost_usd": result.cost_usd,
            "expected": expected,
            "predicted": predicted,
            "score": {
                "expected": score.expected,
                "predicted": score.predicted,
                "matched": score.matched,
                "missed": score.missed,
                "hallucinated": score.hallucinated,
                "precision": score.precision,
                "recall": score.recall,
                "f1": score.f1,
                "fields": {name: asdict(value) | {"precision": value.precision, "recall": value.recall, "f1": value.f1} for name, value in score.fields.items()},
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "sample_id": sample["sample_id"],
            "object_key": sample["object_key"],
            "page_index": sample["page_index"],
            "reference_sha256": sample["reference_sha256"],
            "model": MODEL,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "expected": expected,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples = list(manifest["samples"][:PAGE_COUNT])
    if len(samples) != PAGE_COUNT:
        raise RuntimeError(f"manifest has only {len(samples)} pages; requested {PAGE_COUNT}")
    if not 1 <= MAX_CONCURRENCY <= PAGE_COUNT:
        raise ValueError("concurrency must be between 1 and page count")
    items = _load_texts(samples)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="text-fact-api") as executor:
        futures = [executor.submit(_run, item) for item in items]
        for completed, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            records.append(record)
            print(f"[{completed}/{PAGE_COUNT}] {record['sample_id']} error={record['error']}", flush=True)
    records.sort(key=lambda item: str(item["sample_id"]))
    completed = [record for record in records if not record["error"]]
    expected_total = sum(record["score"]["expected"] for record in completed)
    predicted_total = sum(record["score"]["predicted"] for record in completed)
    matched_total = sum(record["score"]["matched"] for record in completed)
    precision = 1.0 if predicted_total == 0 and expected_total == 0 else (0.0 if predicted_total == 0 else matched_total / predicted_total)
    recall = 1.0 if expected_total == 0 else matched_total / expected_total
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    costs = [float(record["cost_usd"]) for record in completed if record.get("cost_usd") is not None]
    latencies = [int(record["latency_ms"]) for record in completed]
    summary = {
        "requested_pages": PAGE_COUNT,
        "completed_pages": len(completed),
        "failed_pages": PAGE_COUNT - len(completed),
        "expected_facts": expected_total,
        "predicted_facts": predicted_total,
        "matched_facts": matched_total,
        "missed_facts": expected_total - matched_total,
        "hallucinated_facts": predicted_total - matched_total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "pages_with_any_miss": sum(record["score"]["missed"] > 0 for record in completed),
        "pages_with_any_hallucination": sum(record["score"]["hallucinated"] > 0 for record in completed),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "cost_total_usd": sum(costs),
        "cost_per_completed_page_usd": sum(costs) / len(completed) if completed else None,
        "cost_per_1000_pages_usd": sum(costs) * 1000 / len(completed) if completed else None,
        "tokens": {
            key: sum(int(record.get(key) or 0) for record in completed)
            for key in ("input_tokens", "output_tokens", "thinking_tokens", "total_tokens")
        },
    }
    payload = {
        "schema_version": 1,
        "benchmark_kind": "aligned_text_legal_fact_extraction",
        "gold_authority": "deterministic extraction from dual-channel OCR/native admitted text; no model-generated gold",
        "manifest_seed": manifest.get("seed"),
        "model": MODEL,
        "provider_requested": PROVIDER,
        "reasoning": REASONING,
        "prompt": PROMPT_PREFIX,
        "fact_fields": list(FACT_FIELDS),
        "summary": summary,
        "records": records,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (OUTPUT / "records.jsonl").write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8")
    (OUTPUT / "summary.md").write_text(
        f"## Text legal-fact benchmark — {MODEL}\n\n"
        f"- Pages: {len(completed)}/{PAGE_COUNT}\n"
        f"- Facts expected/matched/missed/hallucinated: {expected_total}/{matched_total}/{expected_total - matched_total}/{predicted_total - matched_total}\n"
        f"- Precision / recall / F1: {precision:.6f} / {recall:.6f} / {f1:.6f}\n"
        f"- API latency p50/p95 ms: {summary['latency_p50_ms']} / {summary['latency_p95_ms']}\n"
        f"- Cost total / 1k pages: ${sum(costs):.8f} / ${(summary['cost_per_1000_pages_usd'] or 0):.4f}\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if len(completed) == PAGE_COUNT else 2


if __name__ == "__main__":
    raise SystemExit(main())
