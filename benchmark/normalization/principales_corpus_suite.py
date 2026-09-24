from __future__ import annotations

import hashlib
import inspect
import io
import json
import os
import time
from importlib.metadata import PackageNotFoundError, version
from dataclasses import asdict
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.benchmark_suite import (
    QualityThresholds,
    SuiteRecord,
    aggregate_records,
    evaluate_quality_gates,
    format_summary,
    in_shard,
    modeled_compute_cost,
    parse_configs,
    resume_key,
    source_sha_from_key,
)
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.quality import extract_text_from_structural_json
from scj_page_selection import has_native_text, select_reference_pages

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
CHECKPOINT_PREFIX = "derived/normalization/benchmark/principales-corpus-suite/"
CHECKPOINT_KEY = f"{CHECKPOINT_PREFIX}latest/records.jsonl"

OUTPUT_DIR = Path(
    os.environ.get("SUITE_OUTPUT_DIR", ".artifacts/principales-corpus-suite")
)
CONFIGS = os.environ.get("SUITE_CONFIGS", "pdf_aware")
DOCUMENT_LIMIT = int(os.environ.get("SUITE_DOCUMENT_LIMIT", "25"))
SHARD_INDEX = int(os.environ.get("SUITE_SHARD_INDEX", "0"))
SHARD_COUNT = int(os.environ.get("SUITE_SHARD_COUNT", "1"))
PAGES_PER_DOCUMENT = int(os.environ.get("SUITE_PAGES_PER_DOCUMENT", "3"))
MAX_PAGES_TO_SCAN = int(os.environ.get("SUITE_MAX_PAGES_TO_SCAN", "120"))
MIN_REFERENCE_CHARS = int(os.environ.get("SUITE_MIN_REFERENCE_CHARS", "800"))
RESUME = os.environ.get("SUITE_RESUME", "1") == "1"
REQUIRED_CONFIGS = parse_configs(
    os.environ.get("SUITE_REQUIRED_CONFIGS", "pdf_aware")
)
QUALITY_THRESHOLDS = QualityThresholds(
    max_mean_word_error_rate=float(
        os.environ.get("SUITE_MAX_MEAN_WER", "0.10")
    ),
    min_mean_token_content_recall=float(
        os.environ.get("SUITE_MIN_CONTENT_RECALL", "0.98")
    ),
    min_mean_token_content_precision=float(
        os.environ.get("SUITE_MIN_CONTENT_PRECISION", "0.98")
    ),
    min_aggregate_legal_critical_recall=float(
        os.environ.get("SUITE_MIN_CRITICAL_RECALL", "1.0")
    ),
    min_sampled_document_pass_rate=float(
        os.environ.get("SUITE_MIN_SAMPLED_DOCUMENT_PASS_RATE", "1.0")
    ),
)
OCR_LANGUAGE_TAGS = ("iso:es",)
BENCHMARK_SCHEMA_VERSION = 3
COMPUTE_USD_PER_HOUR = (
    float(os.environ["SUITE_COMPUTE_USD_PER_HOUR"])
    if os.environ.get("SUITE_COMPUTE_USD_PER_HOUR")
    else None
)


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _benchmark_identity(config: str) -> str:
    material = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "config": config,
        "ocr_language_tags": list(OCR_LANGUAGE_TAGS),
        "docling_version": _package_version("docling"),
        "normalizer_source": inspect.getsource(DoclingStructuralNormalizer),
        "scoring_source": inspect.getsource(score_text_fidelity),
        "selector_source": inspect.getsource(select_reference_pages),
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_id() -> str:
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    github_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if github_run_id:
        return f"github-{github_run_id}-attempt-{github_attempt}"
    return f"local-{int(time.time())}"


def _list_pdf_keys(store: Any) -> tuple[str, ...]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": PREFIX,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if key.endswith(".pdf"):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing omitted continuation token")
    return tuple(sorted(keys))


def _download(store: Any, key: str) -> bytes:
    payload = store.client.get_object(
        Bucket=store.config.bucket, Key=key
    )["Body"].read()
    return payload if isinstance(payload, bytes) else bytes(payload)


def _single_page_pdf(pdf_bytes: bytes, page_index: int) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    output = io.BytesIO()
    writer.write(output)
    payload = output.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("single-page PDF extraction did not produce a PDF")
    return payload


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            image = page.render(scale=1.5).to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _normalize(
    *,
    route: str,
    source: bytes,
    page_index: int,
    object_key: str,
    pdf_normalizer: DoclingStructuralNormalizer,
    ocr_normalizer: DoclingStructuralNormalizer,
) -> bytes:
    if route == "pdf_aware":
        page_pdf = _single_page_pdf(source, page_index)
        normalized = pdf_normalizer.normalize(
            page_pdf,
            FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            filename=f"{Path(object_key).stem}-p{page_index + 1}.pdf",
        )
        return normalized.payload
    page_png = _render_page(source, page_index)
    normalized = ocr_normalizer.normalize(
        page_png,
        FormatInspection(
            media_type="image/png",
            detected_format="image/png",
            metadata={},
        ),
        filename=f"{Path(object_key).stem}-p{page_index + 1}.png",
    )
    return normalized.payload


def _load_existing(store: Any) -> tuple[list[SuiteRecord], set[str]]:
    records: list[SuiteRecord] = []
    keys: set[str] = set()
    if not RESUME:
        return records, keys
    try:
        payload = store.client.get_object(
            Bucket=store.config.bucket, Key=CHECKPOINT_KEY
        )["Body"].read()
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return records, keys
        raise
    text = (
        payload.decode("utf-8")
        if isinstance(payload, bytes)
        else str(payload)
    )
    for line in text.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        raw.setdefault("benchmark_identity", "legacy-unversioned")
        record = SuiteRecord(**raw)
        records.append(record)
        keys.add(
            resume_key(
                record.config,
                record.source_sha256,
                record.page_index,
                record.benchmark_identity,
            )
        )
    return records, keys


def main() -> int:
    if DOCUMENT_LIMIT < 0:
        raise ValueError(
            "SUITE_DOCUMENT_LIMIT must be nonnegative (0 means unlimited)"
        )
    if SHARD_COUNT < 1 or SHARD_INDEX < 0 or SHARD_INDEX >= SHARD_COUNT:
        raise ValueError("SUITE_SHARD_INDEX must be within SUITE_SHARD_COUNT")
    if PAGES_PER_DOCUMENT < 1 or PAGES_PER_DOCUMENT > 10:
        raise ValueError("SUITE_PAGES_PER_DOCUMENT must be between 1 and 10")

    configs = parse_configs(CONFIGS)
    missing_required = tuple(
        config for config in REQUIRED_CONFIGS if config not in configs
    )
    if missing_required:
        raise ValueError(
            f"required configurations are not enabled: {missing_required}"
        )
    identities = {
        config: _benchmark_identity(config) for config in configs
    }
    store = build_s3_object_store()
    records, completed = _load_existing(store)

    pdf_normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=OCR_LANGUAGE_TAGS,
        pdf_aware_ocr=True,
    )
    ocr_normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=OCR_LANGUAGE_TAGS,
    )

    keys = _list_pdf_keys(store)
    inventory_sha256 = hashlib.sha256(
        json.dumps(keys, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    keyed = tuple((key, source_sha_from_key(key)) for key in keys)
    shard_keys = tuple(
        (key, sha)
        for key, sha in keyed
        if in_shard(sha, index=SHARD_INDEX, count=SHARD_COUNT)
    )
    if DOCUMENT_LIMIT and len(shard_keys) < DOCUMENT_LIMIT:
        raise RuntimeError(
            f"expected at least {DOCUMENT_LIMIT} PDFs in shard "
            f"{SHARD_INDEX}/{SHARD_COUNT}, found {len(shard_keys)}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUTPUT_DIR / "records.jsonl"
    jsonl_path.write_text(
        "".join(
            json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    coverage: list[dict[str, Any]] = []
    visited_sha: set[str] = set()
    with jsonl_path.open("a", encoding="utf-8") as stream:
        document_index = 0
        for object_key, expected_sha in shard_keys:
            if DOCUMENT_LIMIT and document_index >= DOCUMENT_LIMIT:
                break
            source = _download(store, object_key)
            source_sha256 = hashlib.sha256(source).hexdigest()
            if source_sha256 != expected_sha:
                raise RuntimeError(f"source checksum mismatch for {object_key}")
            if not has_native_text(source):
                coverage.append(
                    {
                        "object_key": object_key,
                        "source_sha256": source_sha256,
                        "status": "no_native_text",
                        "selected_pages": 0,
                    }
                )
                continue
            pages = select_reference_pages(
                source,
                min_reference_chars=MIN_REFERENCE_CHARS,
                max_pages_to_scan=MAX_PAGES_TO_SCAN,
                max_pages_per_document=PAGES_PER_DOCUMENT,
            )
            if not pages:
                coverage.append(
                    {
                        "object_key": object_key,
                        "source_sha256": source_sha256,
                        "status": "no_reference_pages",
                        "selected_pages": 0,
                    }
                )
                continue
            document_index += 1
            visited_sha.add(source_sha256)
            coverage.append(
                {
                    "object_key": object_key,
                    "source_sha256": source_sha256,
                    "status": "sampled",
                    "selected_pages": len(pages),
                    "document_page_count": pages[0].document_page_count,
                }
            )
            for page in pages:
                for config in configs:
                    benchmark_identity = identities[config]
                    key = resume_key(
                        config,
                        source_sha256,
                        page.page_index,
                        benchmark_identity,
                    )
                    if key in completed:
                        continue
                    started = time.perf_counter()
                    payload = _normalize(
                        route=config,
                        source=source,
                        page_index=page.page_index,
                        object_key=object_key,
                        pdf_normalizer=pdf_normalizer,
                        ocr_normalizer=ocr_normalizer,
                    )
                    elapsed = time.perf_counter() - started
                    candidate = extract_text_from_structural_json(payload)
                    score = score_text_fidelity(
                        expected_text=page.text,
                        candidate_text=candidate,
                    )
                    record = SuiteRecord(
                        config=config,
                        source_sha256=source_sha256,
                        object_key=object_key,
                        page_index=page.page_index,
                        document_page_count=page.document_page_count,
                        elapsed_seconds=elapsed,
                        output_bytes=len(payload),
                        character_error_rate=score.character_error_rate,
                        word_error_rate=score.word_error_rate,
                        token_content_recall=score.token_content_recall,
                        token_content_precision=score.token_content_precision,
                        token_order_preservation=(
                            score.token_order_preservation
                        ),
                        legal_critical_recall=score.legal_critical_recall,
                        critical_expected_count=sum(
                            item.expected for item in score.critical.values()
                        ),
                        critical_matched_count=sum(
                            item.matched for item in score.critical.values()
                        ),
                        benchmark_identity=benchmark_identity,
                    )
                    records.append(record)
                    completed.add(key)
                    stream.write(
                        json.dumps(
                            asdict(record), ensure_ascii=False, sort_keys=True
                        )
                        + "\n"
                    )
                    stream.flush()

    active_records = [
        record
        for record in records
        if record.config in identities
        and record.benchmark_identity == identities[record.config]
        and record.source_sha256 in visited_sha
    ]
    report = aggregate_records(active_records)
    for metrics in report.values():
        seconds = float(metrics["speed"]["total_seconds"])
        metrics["cost"]["modeled_normalization_compute_usd"] = (
            modeled_compute_cost(seconds, COMPUTE_USD_PER_HOUR)
        )
    quality_gate = evaluate_quality_gates(
        report,
        required_configs=REQUIRED_CONFIGS,
        thresholds=QUALITY_THRESHOLDS,
    )
    report_payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "configs": list(configs),
        "required_configs": list(REQUIRED_CONFIGS),
        "benchmark_identities": identities,
        "inventory_pdf_count": len(keys),
        "inventory_sha256": inventory_sha256,
        "shard_index": SHARD_INDEX,
        "shard_count": SHARD_COUNT,
        "shard_pdf_count": len(shard_keys),
        "document_limit": DOCUMENT_LIMIT,
        "pages_per_document": PAGES_PER_DOCUMENT,
        "coverage_complete": len(coverage) == len(shard_keys),
        "uninspected_object_keys": [
            key for key, _ in shard_keys[len(coverage):]
        ],
        "coverage_counts": {
            status: sum(item["status"] == status for item in coverage)
            for status in ("sampled", "no_native_text", "no_reference_pages")
        },
        "coverage": coverage,
        "compute_usd_per_hour_assumption": COMPUTE_USD_PER_HOUR,
        "compute_cost_scope": "measured_normalization_seconds_only",
        "recorded_current_identity": len(active_records),
        "checkpoint_record_count": len(records),
        "report": report,
        "quality_gate": quality_gate,
    }
    report_bytes = (
        json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    (OUTPUT_DIR / "report.json").write_bytes(report_bytes)
    (OUTPUT_DIR / "coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = format_summary(
        report,
        recorded=len(active_records),
        quality_gate=quality_gate,
    )
    summary += (
        f"\nShard {SHARD_INDEX}/{SHARD_COUNT}: {len(coverage)}/{len(shard_keys)} "
        "PDFs accounted for; full shard coverage: "
        f"{len(coverage) == len(shard_keys)}. "
        "Statuses and missing contexts are in coverage.json.\n"
    )
    if COMPUTE_USD_PER_HOUR is None:
        summary += "Compute USD estimate unavailable: hourly rate not supplied.\n"
    else:
        summary += (
            f"Compute rate assumption: USD {COMPUTE_USD_PER_HOUR:.4f}/hour. "
            "Modeled cost covers measured normalization seconds only; "
            "see report.json for per-route amounts.\n"
        )
    (OUTPUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(json.dumps(report_payload, indent=2, ensure_ascii=False, sort_keys=True))
    checkpoint_bytes = jsonl_path.read_bytes()
    store.put(
        key=CHECKPOINT_KEY,
        content=checkpoint_bytes,
        content_type="application/x-ndjson",
        metadata={
            "recorded": str(len(records)),
            "schema_version": str(BENCHMARK_SCHEMA_VERSION),
        },
    )
    run_prefix = f"{CHECKPOINT_PREFIX}runs/{_run_id()}/"
    store.put(
        key=f"{run_prefix}records.jsonl",
        content=checkpoint_bytes,
        content_type="application/x-ndjson",
        metadata={"recorded": str(len(records))},
    )
    store.put(
        key=f"{run_prefix}report.json",
        content=report_bytes,
        content_type="application/json",
        metadata={
            "quality_gate_passed": str(bool(quality_gate["passed"])).lower()
        },
    )
    store.put(
        key=f"{run_prefix}coverage.json",
        content=(OUTPUT_DIR / "coverage.json").read_bytes(),
        content_type="application/json",
        metadata={"shard_index": str(SHARD_INDEX), "shard_count": str(SHARD_COUNT)},
    )
    return 0 if quality_gate["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
