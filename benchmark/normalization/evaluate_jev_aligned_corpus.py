"""Evaluate JEV on durable SCJ pages where native text and visual OCR agree.

The benchmark deliberately uses only the immutable corpus-verification dataset in S3.
It does not call a vision model. Pages are split by document, never randomly by page,
and every sampled input keeps hashes/provenance so a third party can reproduce it.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import random
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.decision_batching import DecisionBatchPolicy, DecisionRecord
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator

BASE_PREFIX = "benchmarks/scj-principales/corpus-verification/v1/"
OUTPUT = Path(
    os.environ.get(
        "JEV_ALIGNED_OUTPUT",
        ".artifacts/jev-aligned-corpus.json",
    )
)
MAX_PAGES = int(os.environ.get("JEV_ALIGNED_MAX_PAGES", "240"))
MAX_PAGES_PER_DOCUMENT = int(os.environ.get("JEV_ALIGNED_MAX_PAGES_PER_DOCUMENT", "10"))
EXCERPT_CHARS = int(os.environ.get("JEV_ALIGNED_EXCERPT_CHARS", "3500"))
MAX_COST_USD = float(os.environ.get("JEV_ALIGNED_MAX_COST_USD", "0.03"))
SEED = int(os.environ.get("JEV_ALIGNED_SEED", "20260930"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list(store: Any, prefix: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
        rows.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            return rows
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing omitted continuation token")


def _get(store: Any, key: str) -> bytes:
    response = store.client.get_object(Bucket=store.config.bucket, Key=key)
    body = response["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _latest_complete_prefix(store: Any) -> tuple[str, dict[str, Any]]:
    successes = [
        row
        for row in _list(store, BASE_PREFIX)
        if str(row.get("Key") or "").endswith("/_SUCCESS.json")
    ]
    if not successes:
        raise RuntimeError("no completed SCJ corpus-verification dataset found")
    latest = max(successes, key=lambda row: row.get("LastModified"))
    key = str(latest["Key"])
    success = json.loads(_get(store, key))
    return key.removesuffix("/_SUCCESS.json"), success


def _archive_files(payload: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
        with tarfile.open(mode="r:", fileobj=compressed) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                source = archive.extractfile(member)
                if source is not None:
                    result[member.name] = source.read()
    return result


def _load_aligned_pages(
    store: Any,
    prefix: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pages: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    archives = [
        str(row.get("Key") or "")
        for row in _list(store, f"{prefix}/documents/")
        if str(row.get("Key") or "").endswith(".tar.gz")
    ]
    for key in sorted(archives):
        files = _archive_files(_get(store, key))
        document = json.loads(files["document.json"])
        object_key = str(document["object_key"])
        document_id = Path(key).name.removesuffix(".tar.gz")
        records = [
            json.loads(line)
            for line in files["pages.jsonl"].decode("utf-8").splitlines()
            if line.strip()
        ]
        for record in records:
            classification = str(record.get("classification") or "unknown")
            counts[classification] += 1
            if classification != "aligned":
                continue
            page_index = int(record["page_index"])
            relative = f"reference-text/page-{page_index:05d}.txt"
            raw = files.get(relative)
            if raw is None:
                raise RuntimeError(
                    f"aligned page omitted reference text: {key}:{page_index}"
                )
            text = raw.decode("utf-8")
            if hashlib.sha256(text.encode()).hexdigest() != record["native_text_sha256"]:
                raise RuntimeError("durable aligned reference text SHA mismatch")
            pages.append(
                {
                    "document_id": document_id,
                    "object_key": object_key,
                    "source_pdf_sha256": document["source_pdf_sha256"],
                    "page_index": page_index,
                    "text": text,
                    "native_text_sha256": record["native_text_sha256"],
                    "ocr_text_sha256": record["ocr_text_sha256"],
                    "render_sha256": record.get("render_sha256"),
                    "ocr_mean_confidence": record.get("ocr_mean_confidence"),
                    "alignment": record.get("assessment"),
                }
            )
    return pages, dict(sorted(counts.items()))


def _document_split(document_ids: list[str]) -> dict[str, str]:
    ordered = sorted(set(document_ids))
    random.Random(SEED).shuffle(ordered)
    split: dict[str, str] = {}
    for index, document_id in enumerate(ordered):
        bucket = index % 5
        split[document_id] = (
            "certification"
            if bucket == 4
            else ("validation" if bucket == 3 else "discovery")
        )
    return split


def _sample(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_document: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        by_document.setdefault(str(page["document_id"]), []).append(page)
    rng = random.Random(SEED)
    selected: list[dict[str, Any]] = []
    for document_id in sorted(by_document):
        rows = sorted(
            by_document[document_id],
            key=lambda row: int(row["page_index"]),
        )
        if len(rows) > MAX_PAGES_PER_DOCUMENT:
            rows = rng.sample(rows, MAX_PAGES_PER_DOCUMENT)
            rows.sort(key=lambda row: int(row["page_index"]))
        selected.extend(rows)
    if len(selected) > MAX_PAGES:
        selected = rng.sample(selected, MAX_PAGES)
    return sorted(
        selected,
        key=lambda row: (str(row["document_id"]), int(row["page_index"])),
    )


def main() -> int:
    if not 10 <= MAX_PAGES <= 1000:
        raise ValueError("JEV_ALIGNED_MAX_PAGES must be between 10 and 1000")
    if not 1 <= MAX_PAGES_PER_DOCUMENT <= 50:
        raise ValueError("invalid per-document sample cap")
    if not 1000 <= EXCERPT_CHARS <= 6000:
        raise ValueError("invalid excerpt size")
    if not 0 < MAX_COST_USD <= 0.05:
        raise ValueError("aligned benchmark cost cap must be >0 and <=0.05")

    store = build_s3_object_store()
    dataset_prefix, success = _latest_complete_prefix(store)
    pages, census_counts = _load_aligned_pages(store, dataset_prefix)
    if not pages:
        raise RuntimeError("completed corpus contains no aligned pages")

    splits = _document_split([str(page["document_id"]) for page in pages])
    sample = _sample(pages)
    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    provider = OpenRouterDecisionProvider(
        api_key=settings.api_key.get_secret_value(),
        model=models.jev_model,
    )
    evaluator = JevBatchQualityEvaluator(
        provider=provider,
        policy=DecisionBatchPolicy(
            max_context_tokens=32_000,
            target_total_tokens=24_000,
            reserved_instruction_tokens=4_000,
            max_records_per_batch=20,
        ),
    )
    records = tuple(
        DecisionRecord(
            record_id=f"{row['document_id']}:{row['page_index']}",
            text=str(row["text"])[:EXCERPT_CHARS],
            metadata={
                "source": "SCJ",
                "collection": "principales-sentencias-aligned",
                "document_id": row["document_id"],
                "page_index": row["page_index"],
                "split": splits[str(row["document_id"])],
            },
        )
        for row in sample
    )
    evaluation = evaluator.evaluate(
        records=records,
        state_description=(
            "Every record is from a durable SCJ page where native PDF text and an "
            "independent OCR of the rendered page passed the frozen alignment gate. "
            "Judge observable text quality only. Do not infer visual facts."
        ),
    )
    decisions = {item.record_id: item.probabilities for item in evaluation.records}
    total_cost = sum(batch.cost_usd or 0.0 for batch in evaluation.batches)
    if total_cost > MAX_COST_USD:
        raise RuntimeError(
            f"aligned JEV benchmark exceeded cost cap: ${total_cost:.6f}"
        )

    traces = []
    split_counts: Counter[str] = Counter()
    visual_needed = 0
    for row in sample:
        record_id = f"{row['document_id']}:{row['page_index']}"
        probabilities = decisions[record_id]
        split = splits[str(row["document_id"])]
        split_counts[split] += 1
        if probabilities.needs_visual_review >= 0.5:
            visual_needed += 1
        traces.append(
            {
                **{key: value for key, value in row.items() if key != "text"},
                "split": split,
                "input_text_sha256": _sha(
                    str(row["text"])[:EXCERPT_CHARS].encode()
                ),
                "jev": {
                    "acceptable_probability": probabilities.acceptable,
                    "material_error_probability": probabilities.material_error,
                    "uncertain_probability": probabilities.uncertain,
                    "legal_critical_damage_probability": (
                        probabilities.legal_critical_damage
                    ),
                    "needs_visual_review_probability": (
                        probabilities.needs_visual_review
                    ),
                },
            }
        )

    result = {
        "schema_version": 1,
        "mode": "jev_only",
        "vision_judge_enabled": False,
        "dataset": {
            "prefix": dataset_prefix,
            "success": success,
            "census_page_counts": census_counts,
            "aligned_pages_available": len(pages),
            "aligned_documents_available": len(
                {row["document_id"] for row in pages}
            ),
        },
        "sampling": {
            "seed": SEED,
            "max_pages": MAX_PAGES,
            "max_pages_per_document": MAX_PAGES_PER_DOCUMENT,
            "sampled_pages": len(sample),
            "sampled_documents": len(
                {row["document_id"] for row in sample}
            ),
            "split_page_counts": dict(sorted(split_counts.items())),
            "split_unit": "document",
        },
        "results": {
            "needs_visual_evidence_at_0_5": visual_needed,
            "needs_visual_evidence_share": visual_needed / len(sample),
            "cost_usd": total_cost,
            "batch_count": len(evaluation.batches),
        },
        "telemetry": [
            {
                "batch_index": batch.batch_index,
                "response_id": batch.response_id,
                "provider": batch.provider,
                "model": batch.model,
                "model_version": batch.model_version,
                "input_tokens": batch.input_tokens,
                "output_tokens": batch.output_tokens,
                "total_tokens": batch.total_tokens,
                "cost_usd": batch.cost_usd,
                "latency_ms": batch.latency_ms,
            }
            for batch in evaluation.batches
        ],
        "traces": traces,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "dataset": result["dataset"],
                "sampling": result["sampling"],
                "results": result["results"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
