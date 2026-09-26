from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.gold import assess_reference_text_health, score_text_fidelity
from jurisnexo.normalization.visual_corpus_benchmark import VisualCorpusRecord, aggregate_visual_records

from scj_principales_visual_smoke import PREFIX

OUTPUT = Path(os.environ.get("SCJ_VISUAL_CORPUS_OUTPUT", "scj-visual-corpus-output"))
MANIFEST = Path(os.environ.get("SCJ_VISUAL_CORPUS_MANIFEST", "scj-visual-corpus-manifest.json"))
MODEL = os.environ["JURISNEXO_OPENROUTER_VISUAL_MODEL"]
PROVIDER = os.environ.get("SCJ_VISUAL_PROVIDER", "")
STRUCTURED_MODE = os.environ.get("SCJ_VISUAL_STRUCTURED_MODE", "json_schema")
REASONING = os.environ.get("SCJ_VISUAL_REASONING", "none")
PAGE_COUNT = int(os.environ.get("SCJ_VISUAL_PAGE_COUNT", "100"))
MAX_COST_USD = float(os.environ.get("SCJ_VISUAL_MAX_COST_USD", "0.50"))
SEED = os.environ.get("SCJ_VISUAL_CORPUS_SEED", "jurisnexo-principales-visual-v1")


def _list_pdf_keys(store: Any) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": store.config.bucket, "Prefix": PREFIX, "MaxKeys": 1000}
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
            raise RuntimeError("S3 listing truncated without continuation token")
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
    import io
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=2.0)
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _download(store: Any, key: str) -> bytes:
    body = store.client.get_object(Bucket=store.config.bucket, Key=key)["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def build_manifest() -> dict[str, Any]:
    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    rng = random.Random(SEED)
    rng.shuffle(keys)
    samples: list[dict[str, Any]] = []
    for key in keys:
        if len(samples) >= PAGE_COUNT:
            break
        try:
            source = _download(store, key)
            count = _page_count(source)
        except Exception:
            continue
        if count < 1:
            continue
        indexes = list(range(count))
        rng.shuffle(indexes)
        for page_index in indexes[: min(count, 40)]:
            try:
                text = _native_text(source, page_index)
            except Exception:
                continue
            if len(text.strip()) < 800:
                continue
            health = assess_reference_text_health(text)
            if not health.is_reliable:
                continue
            image = _render_page(source, page_index)
            samples.append({
                "sample_id": f"{hashlib.sha256(key.encode()).hexdigest()[:12]}-p{page_index + 1}",
                "object_key": key,
                "page_index": page_index,
                "reference_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "reference_characters": len(text),
            })
            break
    if len(samples) != PAGE_COUNT:
        raise RuntimeError(f"needed {PAGE_COUNT} eligible pages, found {len(samples)}")
    payload = {
        "schema_version": 1,
        "seed": SEED,
        "page_count": PAGE_COUNT,
        "selection": "one deterministic pseudo-random born-digital body page per distinct PDF",
        "samples": samples,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest_pages": len(samples), "seed": SEED}, sort_keys=True))
    return payload


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "transcription": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "unreadable": {"type": "boolean"},
        },
        "required": ["transcription", "confidence", "unreadable"],
        "additionalProperties": False,
    }


def _provider() -> OpenRouterVisualModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return OpenRouterVisualModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=MODEL,
        base_url=settings.base_url,
        timeout_seconds=45.0,
        reasoning_effort=REASONING,
        structured_mode=STRUCTURED_MODE,  # type: ignore[arg-type]
        provider_order=(PROVIDER,) if PROVIDER else (),
        allow_provider_fallbacks=False,
    )


def _record_error(sample_id: str, message: str) -> VisualCorpusRecord:
    return VisualCorpusRecord(
        sample_id=sample_id, model=MODEL, latency_ms=0, input_tokens=None,
        output_tokens=None, thinking_tokens=None, cost_usd=None,
        character_error_rate=0.0, word_error_rate=0.0, token_content_recall=0.0,
        token_content_precision=0.0, token_content_f1=0.0, token_order_preservation=0.0,
        legal_critical_recall=0.0, critical_expected_count=0, critical_matched_count=0,
        reference_reliable=False, model_confidence=None, unreadable=False,
        routed_provider="", error=message,
    )


def run_model() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples = manifest["samples"]
    if len(samples) != PAGE_COUNT:
        raise RuntimeError(f"manifest has {len(samples)} pages, expected {PAGE_COUNT}")
    store = build_s3_object_store()
    provider = _provider()
    records: list[VisualCorpusRecord] = []
    details: list[dict[str, Any]] = []
    running_cost = 0.0
    for ordinal, sample in enumerate(samples, start=1):
        sample_id = str(sample["sample_id"])
        try:
            source = _download(store, str(sample["object_key"]))
            reference = _native_text(source, int(sample["page_index"]))
            image = _render_page(source, int(sample["page_index"]))
            if hashlib.sha256(reference.encode("utf-8")).hexdigest() != sample["reference_sha256"]:
                raise RuntimeError("reference drift from frozen manifest")
            if hashlib.sha256(image).hexdigest() != sample["image_sha256"]:
                raise RuntimeError("render drift from frozen manifest")
            health = assess_reference_text_health(reference)
            started = time.perf_counter()
            result = provider.verify_image_text(
                image=image,
                media_type="image/jpeg",
                prompt=(
                    "Transcribe every readable word on this legal-document page exactly as visible, "
                    "preserving reading order. Do not summarize, correct spelling, infer missing text, "
                    "or add commentary. Set unreadable=true only when the page cannot be reliably read. "
                    "Confidence is your confidence in the transcription from 0 to 1."
                ),
                json_schema=_schema(),
                max_output_tokens=8000,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            transcription = str(result.value.get("transcription") or "")
            score = score_text_fidelity(expected_text=reference, candidate_text=transcription)
            expected_critical = sum(item.expected for item in score.critical.values())
            matched_critical = sum(item.matched for item in score.critical.values())
            cost = result.cost_usd or 0.0
            running_cost += cost
            record = VisualCorpusRecord(
                sample_id=sample_id,
                model=result.model,
                latency_ms=latency_ms,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                thinking_tokens=result.usage.thinking_tokens,
                cost_usd=result.cost_usd,
                character_error_rate=score.character_error_rate,
                word_error_rate=score.word_error_rate,
                token_content_recall=score.token_content_recall,
                token_content_precision=score.token_content_precision,
                token_content_f1=score.token_content_f1,
                token_order_preservation=score.token_order_preservation,
                legal_critical_recall=score.legal_critical_recall,
                critical_expected_count=expected_critical,
                critical_matched_count=matched_critical,
                reference_reliable=health.is_reliable,
                model_confidence=float(result.value.get("confidence") or 0.0),
                unreadable=bool(result.value.get("unreadable", False)),
                routed_provider=str((result.provider_metadata or {}).get("routed_provider") or ""),
            )
            records.append(record)
            details.append({**asdict(record), "object_key": sample["object_key"], "page_index": sample["page_index"]})
        except (ModelProviderError, Exception) as exc:
            records.append(_record_error(sample_id, f"{type(exc).__name__}: {exc}"))
        if running_cost > MAX_COST_USD:
            raise RuntimeError(f"cost cap exceeded after page {ordinal}: ${running_cost:.6f} > ${MAX_COST_USD:.2f}")
        print(f"[{ordinal}/{PAGE_COUNT}] {sample_id} cost=${running_cost:.6f}", flush=True)

    summary = aggregate_visual_records(records, expected_pages=PAGE_COUNT)
    payload = {
        "schema_version": 1,
        "manifest_seed": manifest["seed"],
        "manifest_page_count": len(samples),
        "model": MODEL,
        "provider_requested": PROVIDER,
        "structured_mode": STRUCTURED_MODE,
        "reasoning": REASONING,
        "max_cost_usd": MAX_COST_USD,
        "summary": summary,
        "records": details,
        "failures": [asdict(record) for record in records if record.error],
        "interpretation": {
            "reference": "born-digital native PDF text; reliable pages only are scored",
            "potential_error": "a disagreement with native text, not automatically a proven visual error",
            "promotion": "benchmark evidence only; no model is promoted by this run alone",
        },
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (OUTPUT / "records.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in details), encoding="utf-8")
    quality = summary["quality"]
    cost = summary["cost"]
    latency = summary["latency"]
    markdown = (
        f"## Visual corpus — {MODEL}\n\n"
        f"- Pages: {summary['completed_pages']}/{PAGE_COUNT} (failures: {summary['failed_pages']})\n"
        f"- Mean WER: {quality['mean_word_error_rate']} | p95 WER: {quality['p95_word_error_rate']}\n"
        f"- Critical recall: {quality['aggregate_legal_critical_recall']}\n"
        f"- Potential-error pages: {quality['pages_with_potential_error']} ({quality['potential_error_page_rate']})\n"
        f"- Latency p50/p95/max ms: {latency['p50_ms']} / {latency['p95_ms']} / {latency['max_ms']}\n"
        f"- Cost total/page/1000 pages: ${cost['total_usd']:.6f} / ${cost['mean_per_completed_page_usd'] or 0:.6f} / ${cost['projected_per_1000_pages_usd'] or 0:.4f}\n"
        f"- Tokens input/output/thinking: {summary['tokens']['input_total']} / {summary['tokens']['output_total']} / {summary['tokens']['thinking_total']}\n"
    )
    (OUTPUT / "summary.md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"model": MODEL, "summary": summary}, ensure_ascii=False, sort_keys=True))
    return 0 if summary["failed_pages"] == 0 else 1


def main() -> int:
    mode = os.environ.get("SCJ_VISUAL_CORPUS_MODE", "run")
    if mode == "manifest":
        build_manifest()
        return 0
    if mode == "run":
        return run_model()
    raise ValueError(f"unknown SCJ_VISUAL_CORPUS_MODE: {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
