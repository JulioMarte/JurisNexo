from __future__ import annotations

import hashlib
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import (
    OpenRouterVisualModelProvider,
    StructuredMode,
)
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.visual_corpus_benchmark import (
    VisualCorpusRecord,
    aggregate_visual_records,
)

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
OUTPUT = Path(
    os.environ.get(
        "SCJ_VISUAL_CORPUS_OUTPUT",
        "scj-visual-corpus-output",
    )
)
MANIFEST = Path(
    os.environ.get(
        "SCJ_VISUAL_CORPUS_MANIFEST",
        "scj-visual-corpus-manifest.json",
    )
)
MODEL = os.environ["JURISNEXO_OPENROUTER_VISUAL_MODEL"]
PROVIDER = os.environ.get("SCJ_VISUAL_PROVIDER", "")
STRUCTURED_MODE = os.environ.get(
    "SCJ_VISUAL_STRUCTURED_MODE",
    "raw_text",
)
REASONING = os.environ.get("SCJ_VISUAL_REASONING", "none")
PAGE_COUNT = int(os.environ.get("SCJ_VISUAL_PAGE_COUNT", "1"))
MAX_CONCURRENCY = int(
    os.environ.get(
        "SCJ_VISUAL_MAX_CONCURRENCY",
        str(PAGE_COUNT),
    )
)

TRANSCRIPTION_PROMPT = (
    "Transcribe every visible word exactly as written. "
    "Return only the transcription. "
    "Do not return JSON or a schema. "
    "Do not explain, summarize, correct spelling, or infer missing text."
)


@dataclass(frozen=True, slots=True)
class PreparedSample:
    sample: dict[str, Any]
    reference: str
    image: bytes
    preparation_ms: int


def _list_pdf_keys(store: Any) -> list[str]:
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
        keys.extend(
            str(item.get("Key") or "")
            for item in response.get("Contents", [])
            if str(item.get("Key") or "").endswith(".pdf")
        )
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError(
                "S3 listing truncated without continuation token"
            )
    return sorted(set(keys))


def _page_count(pdf_bytes: bytes) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(document)
    finally:
        document.close()


def _native_text(pdf_bytes: bytes, page_index: int) -> str:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            text_page = page.get_textpage()
            try:
                return text_page.get_text_range()
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=2.0)
            try:
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=88,
                    optimize=True,
                )
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _download(store: Any, key: str) -> bytes:
    body = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"transcription": {"type": "string"}},
        "required": ["transcription"],
        "additionalProperties": False,
    }


def _provider() -> OpenRouterVisualModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    allowed_modes = {
        "tool",
        "json_schema",
        "json_object",
        "prompt_json",
        "raw_text",
    }
    if STRUCTURED_MODE not in allowed_modes:
        raise ValueError(
            f"invalid structured mode: {STRUCTURED_MODE}"
        )
    mode: StructuredMode = STRUCTURED_MODE  # type: ignore[assignment]
    return OpenRouterVisualModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=MODEL,
        base_url=settings.base_url,
        timeout_seconds=120.0,
        reasoning_effort=REASONING,
        structured_mode=mode,
        provider_order=(PROVIDER,) if PROVIDER else (),
        allow_provider_fallbacks=not bool(PROVIDER),
    )


def _prepare_samples(
    samples: list[dict[str, Any]],
) -> list[PreparedSample]:
    store = build_s3_object_store()
    prepared: list[PreparedSample] = []
    cached_key = ""
    source = b""
    for position, sample in enumerate(samples, start=1):
        started = time.perf_counter()
        key = str(sample["object_key"])
        if key != cached_key:
            source = _download(store, key)
            cached_key = key
        page_index = int(sample["page_index"])
        reference = _native_text(source, page_index)
        image = _render_page(source, page_index)
        reference_sha = hashlib.sha256(
            reference.encode("utf-8")
        ).hexdigest()
        image_sha = hashlib.sha256(image).hexdigest()
        if reference_sha != sample["reference_sha256"]:
            raise RuntimeError(
                f"reference drift: {sample['sample_id']}"
            )
        if image_sha != sample["image_sha256"]:
            raise RuntimeError(
                f"render drift: {sample['sample_id']}"
            )
        prepared.append(
            PreparedSample(
                sample=sample,
                reference=reference,
                image=image,
                preparation_ms=int(
                    (time.perf_counter() - started) * 1000
                ),
            )
        )
        print(
            f"[prepare {position}/{len(samples)}] "
            f"{sample['sample_id']}",
            flush=True,
        )
    return prepared


def _record_error(
    sample_id: str,
    message: str,
    latency_ms: int,
) -> VisualCorpusRecord:
    return VisualCorpusRecord(
        sample_id=sample_id,
        model=MODEL,
        latency_ms=latency_ms,
        input_tokens=None,
        output_tokens=None,
        thinking_tokens=None,
        cost_usd=None,
        character_error_rate=0.0,
        word_error_rate=0.0,
        token_content_recall=0.0,
        token_content_precision=0.0,
        token_content_f1=0.0,
        token_order_preservation=0.0,
        legal_critical_recall=0.0,
        critical_expected_count=0,
        critical_matched_count=0,
        reference_reliable=False,
        model_confidence=None,
        unreadable=False,
        routed_provider="",
        error=message,
    )


def _is_transient_provider_error(exc: ModelProviderError) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in (
            "HTTP 429",
            "HTTP 500",
            "HTTP 502",
            "HTTP 503",
            "HTTP 504",
        )
    )


def _token_breakdown(
    *,
    input_tokens: int | None,
    completion_tokens: int | None,
    reasoning_tokens: int | None,
    total_tokens: int | None,
) -> dict[str, int | None]:
    answer_tokens: int | None = None
    if completion_tokens is not None:
        answer_tokens = max(
            0,
            completion_tokens - (reasoning_tokens or 0),
        )
    return {
        "input_tokens": input_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "answer_tokens_estimated": answer_tokens,
        "total_tokens": total_tokens,
    }


def _run_prepared(
    item: PreparedSample,
) -> tuple[VisualCorpusRecord, dict[str, Any]]:
    sample = item.sample
    sample_id = str(sample["sample_id"])
    api_started = time.perf_counter()
    retry_count = 0
    try:
        provider = _provider()
        while True:
            try:
                result = provider.verify_image_text(
                    image=item.image,
                    media_type="image/jpeg",
                    prompt=TRANSCRIPTION_PROMPT,
                    json_schema=_schema(),
                    max_output_tokens=None,
                )
                break
            except ModelProviderError as exc:
                if (
                    retry_count >= 2
                    or not _is_transient_provider_error(exc)
                ):
                    raise
                time.sleep(0.5 * (2**retry_count))
                retry_count += 1

        api_latency_ms = int(
            (time.perf_counter() - api_started) * 1000
        )
        transcription = str(
            result.value.get("transcription") or ""
        )
        score = score_text_fidelity(
            expected_text=item.reference,
            candidate_text=transcription,
        )
        expected = sum(
            item.expected for item in score.critical.values()
        )
        matched = sum(
            item.matched for item in score.critical.values()
        )
        record = VisualCorpusRecord(
            sample_id=sample_id,
            model=result.model,
            latency_ms=api_latency_ms,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            thinking_tokens=result.usage.thinking_tokens,
            cost_usd=result.cost_usd,
            character_error_rate=score.character_error_rate,
            word_error_rate=score.word_error_rate,
            token_content_recall=score.token_content_recall,
            token_content_precision=score.token_content_precision,
            token_content_f1=score.token_content_f1,
            token_order_preservation=(
                score.token_order_preservation
            ),
            legal_critical_recall=score.legal_critical_recall,
            critical_expected_count=expected,
            critical_matched_count=matched,
            reference_reliable=True,
            model_confidence=None,
            unreadable=False,
            routed_provider=str(
                (result.provider_metadata or {}).get(
                    "routed_provider"
                )
                or ""
            ),
        )
        detail = {
            **asdict(record),
            "object_key": sample["object_key"],
            "page_index": sample["page_index"],
            "reference_characters": len(item.reference),
            "reference_text": item.reference,
            "reference_sha256": hashlib.sha256(
                item.reference.encode("utf-8")
            ).hexdigest(),
            "transcription_characters": len(transcription),
            "transcription": transcription,
            "preparation_ms": item.preparation_ms,
            "api_latency_ms": api_latency_ms,
            "retry_count": retry_count,
            "tokens": _token_breakdown(
                input_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                reasoning_tokens=result.usage.thinking_tokens,
                total_tokens=result.usage.total_tokens,
            ),
        }
        return record, detail
    except Exception as exc:
        elapsed = int(
            (time.perf_counter() - api_started) * 1000
        )
        record = _record_error(
            sample_id,
            f"{type(exc).__name__}: {exc}",
            elapsed,
        )
        return record, {
            **asdict(record),
            "object_key": sample["object_key"],
            "page_index": sample["page_index"],
            "reference_characters": len(item.reference),
            "reference_text": item.reference,
            "reference_sha256": hashlib.sha256(
                item.reference.encode("utf-8")
            ).hexdigest(),
            "transcription_characters": 0,
            "transcription": "",
            "preparation_ms": item.preparation_ms,
            "api_latency_ms": elapsed,
            "retry_count": retry_count,
            "tokens": _token_breakdown(
                input_tokens=None,
                completion_tokens=None,
                reasoning_tokens=None,
                total_tokens=None,
            ),
        }


def _aggregate_token_breakdown(
    details: list[dict[str, Any]],
) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "answer_tokens_estimated": 0,
        "total_tokens": 0,
    }
    for detail in details:
        tokens = detail["tokens"]
        for key in totals:
            value = tokens.get(key)
            if isinstance(value, int):
                totals[key] += value
    return totals


def run_model() -> int:
    manifest = json.loads(
        MANIFEST.read_text(encoding="utf-8")
    )
    samples = manifest["samples"]
    if len(samples) != PAGE_COUNT:
        raise RuntimeError(
            f"manifest has {len(samples)} pages, "
            f"expected {PAGE_COUNT}"
        )
    if not 1 <= MAX_CONCURRENCY <= PAGE_COUNT:
        raise ValueError(
            "SCJ_VISUAL_MAX_CONCURRENCY must be between "
            "1 and page count"
        )

    preparation_started = time.perf_counter()
    prepared = _prepare_samples(samples)
    preparation_ms = int(
        (time.perf_counter() - preparation_started) * 1000
    )

    records: list[VisualCorpusRecord] = []
    details: list[dict[str, Any]] = []
    api_started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=MAX_CONCURRENCY,
        thread_name_prefix="visual-api",
    ) as executor:
        futures = [
            executor.submit(_run_prepared, item)
            for item in prepared
        ]
        for completed, future in enumerate(
            as_completed(futures),
            start=1,
        ):
            record, detail = future.result()
            records.append(record)
            details.append(detail)
            print(
                f"[api {completed}/{PAGE_COUNT}] "
                f"{record.sample_id} "
                f"latency={record.latency_ms}ms "
                f"cost={record.cost_usd}",
                flush=True,
            )

    api_wall_ms = int(
        (time.perf_counter() - api_started) * 1000
    )
    details.sort(key=lambda item: str(item["sample_id"]))
    records.sort(key=lambda item: item.sample_id)

    summary = aggregate_visual_records(
        records,
        expected_pages=PAGE_COUNT,
    )
    summary["token_breakdown"] = _aggregate_token_breakdown(
        details
    )
    summary["concurrency"] = {
        "configured": MAX_CONCURRENCY,
        "preparation_ms": preparation_ms,
        "api_wall_clock_ms": api_wall_ms,
        "throughput_pages_per_second": (
            len(records) / (api_wall_ms / 1000)
            if api_wall_ms
            else None
        ),
    }

    payload = {
        "schema_version": 5,
        "manifest_seed": manifest["seed"],
        "manifest_page_count": len(samples),
        "model": MODEL,
        "provider_requested": PROVIDER,
        "structured_mode": STRUCTURED_MODE,
        "reasoning_request": (
            None if REASONING == "none" else REASONING
        ),
        "prompt": TRANSCRIPTION_PROMPT,
        "output_token_limit": None,
        "max_concurrency": MAX_CONCURRENCY,
        "summary": summary,
        "records": details,
        "failures": [
            asdict(record)
            for record in records
            if record.error
        ],
        "interpretation": {
            "reference": (
                "reliable born-digital native PDF text"
            ),
            "token_semantics": (
                "completion_tokens are provider-reported output "
                "tokens; reasoning_tokens are a subset when the "
                "provider reports them; answer_tokens_estimated is "
                "completion minus reasoning"
            ),
            "latency_ms": (
                "provider call only; excludes S3, PDF parsing "
                "and rendering"
            ),
            "output_limit": (
                "no max_tokens/max_completion_tokens parameter "
                "is sent by JurisNexo"
            ),
        },
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "records.jsonl").write_text(
        "".join(
            json.dumps(
                detail,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for detail in details
        ),
        encoding="utf-8",
    )

    quality = summary["quality"]
    cost = summary["cost"]
    latency = summary["latency"]
    tokens = summary["token_breakdown"]
    markdown = (
        f"## Visual corpus — {MODEL}\n\n"
        f"- Pages: {summary['completed_pages']}/{PAGE_COUNT} "
        f"(failures: {summary['failed_pages']})\n"
        f"- Mean WER: {quality['mean_word_error_rate']}\n"
        f"- Critical recall: "
        f"{quality['aggregate_legal_critical_recall']}\n"
        f"- API latency p50/p95/max ms: "
        f"{latency['p50_ms']} / {latency['p95_ms']} / "
        f"{latency['max_ms']}\n"
        f"- Input/completion/reasoning/answer-est./total tokens: "
        f"{tokens['input_tokens']} / "
        f"{tokens['completion_tokens']} / "
        f"{tokens['reasoning_tokens']} / "
        f"{tokens['answer_tokens_estimated']} / "
        f"{tokens['total_tokens']}\n"
        f"- Cost total/page: "
        f"${cost['total_usd']:.8f} / "
        f"${cost['mean_per_completed_page_usd'] or 0:.8f}\n"
        f"- Output token limit imposed by JurisNexo: none\n"
    )
    (OUTPUT / "summary.md").write_text(
        markdown,
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "model": MODEL,
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["failed_pages"] == 0 else 1


def main() -> int:
    mode = os.environ.get(
        "SCJ_VISUAL_CORPUS_MODE",
        "run",
    )
    if mode == "run":
        return run_model()
    raise ValueError(
        f"unknown SCJ_VISUAL_CORPUS_MODE: {mode}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
