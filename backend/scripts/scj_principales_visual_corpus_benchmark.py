from __future__ import annotations

import hashlib
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider, StructuredMode
from jurisnexo.normalization.gold import assess_reference_text_health, score_text_fidelity
from jurisnexo.normalization.visual_corpus_benchmark import VisualCorpusRecord, aggregate_visual_records
from scj_principales_visual_smoke import PREFIX

OUTPUT = Path(os.environ.get("SCJ_VISUAL_CORPUS_OUTPUT", "scj-visual-corpus-output"))
MANIFEST = Path(os.environ.get("SCJ_VISUAL_CORPUS_MANIFEST", "scj-visual-corpus-manifest.json"))
MODEL = os.environ["JURISNEXO_OPENROUTER_VISUAL_MODEL"]
PROVIDER = os.environ.get("SCJ_VISUAL_PROVIDER", "")
STRUCTURED_MODE = os.environ.get("SCJ_VISUAL_STRUCTURED_MODE", "raw_text")
REASONING = os.environ.get("SCJ_VISUAL_REASONING", "none")
PAGE_COUNT = int(os.environ.get("SCJ_VISUAL_PAGE_COUNT", "100"))
MAX_COST_USD = float(os.environ.get("SCJ_VISUAL_MAX_COST_USD", "0.50"))
SEED = os.environ.get("SCJ_VISUAL_CORPUS_SEED", "jurisnexo-principales-visual-v1")
MAX_CONCURRENCY = int(os.environ.get("SCJ_VISUAL_MAX_CONCURRENCY", str(PAGE_COUNT)))
TRANSCRIPTION_PROMPT = "Transcribe every visible word exactly as written. Return ONLY the transcription. Do not return JSON. Do not return a schema. Do not explain your answer. Do not correct spelling. Do not summarize. Do not infer missing text."

@dataclass(frozen=True, slots=True)
class PreparedSample:
    sample: dict[str, Any]
    reference: str
    image: bytes
    preparation_ms: int


def _list_pdf_keys(store: Any) -> list[str]:
    keys: list[str] = []; token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": store.config.bucket, "Prefix": PREFIX, "MaxKeys": 1000}
        if token: kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        keys.extend(str(item.get("Key") or "") for item in response.get("Contents", []) if str(item.get("Key") or "").endswith(".pdf"))
        if not response.get("IsTruncated"): break
        token = str(response.get("NextContinuationToken") or "")
        if not token: raise RuntimeError("S3 listing truncated without continuation token")
    return sorted(set(keys))


def _page_count(pdf_bytes: bytes) -> int:
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_bytes)
    try: return len(document)
    finally: document.close()


def _native_text(pdf_bytes: bytes, page_index: int) -> str:
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            text_page = page.get_textpage()
            try: return text_page.get_text_range()
            finally: text_page.close()
        finally: page.close()
    finally: document.close()


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import io
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=2.0)
            try:
                image = bitmap.to_pil(); output = io.BytesIO(); image.save(output, format="JPEG", quality=88, optimize=True); return output.getvalue()
            finally:
                bitmap.close()
        finally: page.close()
    finally: document.close()


def _download(store: Any, key: str) -> bytes:
    body = store.client.get_object(Bucket=store.config.bucket, Key=key)["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def build_manifest() -> dict[str, Any]:
    store = build_s3_object_store(); keys = _list_pdf_keys(store); rng = random.Random(SEED); rng.shuffle(keys); samples: list[dict[str, Any]] = []
    for key in keys:
        if len(samples) >= PAGE_COUNT: break
        try: source = _download(store, key); count = _page_count(source)
        except Exception: continue
        indexes = list(range(count)); rng.shuffle(indexes)
        for page_index in indexes[:min(count, 40)]:
            try: text = _native_text(source, page_index)
            except Exception: continue
            if len(text.strip()) < 800 or not assess_reference_text_health(text).is_reliable: continue
            image = _render_page(source, page_index)
            samples.append({"sample_id": f"{hashlib.sha256(key.encode()).hexdigest()[:12]}-p{page_index + 1}", "object_key": key, "page_index": page_index, "reference_sha256": hashlib.sha256(text.encode()).hexdigest(), "image_sha256": hashlib.sha256(image).hexdigest(), "reference_characters": len(text)})
            break
    if len(samples) != PAGE_COUNT: raise RuntimeError(f"needed {PAGE_COUNT} eligible pages, found {len(samples)}")
    payload = {"schema_version": 1, "seed": SEED, "page_count": PAGE_COUNT, "selection": "one deterministic pseudo-random born-digital body page per distinct PDF", "samples": samples}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True); MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n", encoding="utf-8"); return payload


def _schema() -> dict[str, Any]:
    return {"type":"object","properties":{"transcription":{"type":"string"}},"required":["transcription"],"additionalProperties":False}


def _provider() -> OpenRouterVisualModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None: raise RuntimeError("OPENROUTER_API_KEY is required")
    if STRUCTURED_MODE not in {"tool", "json_schema", "json_object", "prompt_json", "raw_text"}: raise ValueError(f"invalid structured mode: {STRUCTURED_MODE}")
    mode: StructuredMode = STRUCTURED_MODE  # type: ignore[assignment]
    return OpenRouterVisualModelProvider(api_key=settings.api_key.get_secret_value(), model=MODEL, base_url=settings.base_url, timeout_seconds=45.0, reasoning_effort=REASONING, structured_mode=mode, provider_order=(PROVIDER,) if PROVIDER else (), allow_provider_fallbacks=False)


def _prepare_samples(samples: list[dict[str, Any]]) -> list[PreparedSample]:
    store = build_s3_object_store(); prepared: list[PreparedSample] = []; cached_key = ""; source = b""
    for position, sample in enumerate(samples, start=1):
        started = time.perf_counter(); key = str(sample["object_key"])
        if key != cached_key: source = _download(store, key); cached_key = key
        page_index = int(sample["page_index"]); reference = _native_text(source, page_index); image = _render_page(source, page_index)
        if hashlib.sha256(reference.encode()).hexdigest() != sample["reference_sha256"]: raise RuntimeError(f"reference drift: {sample['sample_id']}")
        if hashlib.sha256(image).hexdigest() != sample["image_sha256"]: raise RuntimeError(f"render drift: {sample['sample_id']}")
        prepared.append(PreparedSample(sample=sample, reference=reference, image=image, preparation_ms=int((time.perf_counter()-started)*1000)))
        print(f"[prepare {position}/{len(samples)}] {sample['sample_id']}", flush=True)
    return prepared


def _record_error(sample_id: str, message: str, latency_ms: int) -> VisualCorpusRecord:
    return VisualCorpusRecord(sample_id=sample_id, model=MODEL, latency_ms=latency_ms, input_tokens=None, output_tokens=None, thinking_tokens=None, cost_usd=None, character_error_rate=0.0, word_error_rate=0.0, token_content_recall=0.0, token_content_precision=0.0, token_content_f1=0.0, token_order_preservation=0.0, legal_critical_recall=0.0, critical_expected_count=0, critical_matched_count=0, reference_reliable=False, model_confidence=None, unreadable=False, routed_provider="", error=message)


def _run_prepared(item: PreparedSample) -> tuple[VisualCorpusRecord, dict[str, Any]]:
    sample = item.sample; sample_id = str(sample["sample_id"]); api_started = time.perf_counter()
    try:
        result = _provider().verify_image_text(image=item.image, media_type="image/jpeg", prompt=TRANSCRIPTION_PROMPT, json_schema=_schema(), max_output_tokens=8000)
        api_ms = int((time.perf_counter()-api_started)*1000); transcription = str(result.value.get("transcription") or ""); score = score_text_fidelity(expected_text=item.reference, candidate_text=transcription); expected = sum(x.expected for x in score.critical.values()); matched = sum(x.matched for x in score.critical.values())
        record = VisualCorpusRecord(sample_id=sample_id, model=result.model, latency_ms=api_ms, input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens, thinking_tokens=result.usage.thinking_tokens, cost_usd=result.cost_usd, character_error_rate=score.character_error_rate, word_error_rate=score.word_error_rate, token_content_recall=score.token_content_recall, token_content_precision=score.token_content_precision, token_content_f1=score.token_content_f1, token_order_preservation=score.token_order_preservation, legal_critical_recall=score.legal_critical_recall, critical_expected_count=expected, critical_matched_count=matched, reference_reliable=True, model_confidence=None, unreadable=False, routed_provider=str((result.provider_metadata or {}).get("routed_provider") or ""))
        return record, {**asdict(record), "object_key":sample["object_key"], "page_index":sample["page_index"], "preparation_ms":item.preparation_ms, "api_latency_ms":api_ms}
    except Exception as exc:
        elapsed=int((time.perf_counter()-api_started)*1000); record=_record_error(sample_id, f"{type(exc).__name__}: {exc}", elapsed); return record,{**asdict(record),"object_key":sample["object_key"],"page_index":sample["page_index"],"preparation_ms":item.preparation_ms,"api_latency_ms":elapsed}


def run_model() -> int:
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8")); samples=manifest["samples"]
    if len(samples)!=PAGE_COUNT: raise RuntimeError(f"manifest has {len(samples)} pages, expected {PAGE_COUNT}")
    if not 1 <= MAX_CONCURRENCY <= PAGE_COUNT: raise ValueError("SCJ_VISUAL_MAX_CONCURRENCY must be between 1 and page count")
    preparation_started=time.perf_counter(); prepared=_prepare_samples(samples); preparation_ms=int((time.perf_counter()-preparation_started)*1000)
    records: list[VisualCorpusRecord]=[]; details: list[dict[str,Any]]=[]; running_cost=0.0; api_started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="visual-api") as executor:
        futures=[executor.submit(_run_prepared,item) for item in prepared]
        for completed,future in enumerate(as_completed(futures),start=1):
            record,detail=future.result(); records.append(record); details.append(detail); running_cost += record.cost_usd or 0.0; print(f"[api {completed}/{PAGE_COUNT}] {record.sample_id} latency={record.latency_ms}ms cost=${running_cost:.6f}",flush=True)
    api_wall_ms=int((time.perf_counter()-api_started)*1000)
    if running_cost>MAX_COST_USD: raise RuntimeError(f"cost cap exceeded: ${running_cost:.6f} > ${MAX_COST_USD:.2f}")
    details.sort(key=lambda x:str(x["sample_id"])); records.sort(key=lambda x:x.sample_id); summary=aggregate_visual_records(records,expected_pages=PAGE_COUNT); summary["concurrency"]={"configured":MAX_CONCURRENCY,"preparation_ms":preparation_ms,"api_wall_clock_ms":api_wall_ms,"throughput_pages_per_second":len(records)/(api_wall_ms/1000) if api_wall_ms else None}
    payload={"schema_version":4,"manifest_seed":manifest["seed"],"manifest_page_count":len(samples),"model":MODEL,"provider_requested":PROVIDER,"structured_mode":STRUCTURED_MODE,"reasoning":REASONING,"prompt":TRANSCRIPTION_PROMPT,"max_cost_usd":MAX_COST_USD,"max_concurrency":MAX_CONCURRENCY,"summary":summary,"records":details,"failures":[asdict(r) for r in records if r.error],"interpretation":{"reference":"born-digital native PDF text; all PDF/S3 preparation completes before model requests begin","latency_ms":"provider call only; excludes S3, PDF parsing and rendering","promotion":"benchmark evidence only; no model is promoted by this run alone"}}
    OUTPUT.mkdir(parents=True,exist_ok=True); (OUTPUT/"report.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8"); (OUTPUT/"records.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in details),encoding="utf-8")
    quality=summary["quality"]; cost=summary["cost"]; latency=summary["latency"]; concurrency=summary["concurrency"]
    markdown=f"## Visual corpus — {MODEL}\n\n- Pages: {summary['completed_pages']}/{PAGE_COUNT} (failures: {summary['failed_pages']})\n- Preparation: {preparation_ms} ms | API wall clock: {api_wall_ms} ms | concurrency: {MAX_CONCURRENCY}\n- API throughput: {concurrency['throughput_pages_per_second']:.3f} pages/s\n- Mean WER: {quality['mean_word_error_rate']} | p95 WER: {quality['p95_word_error_rate']}\n- Critical recall: {quality['aggregate_legal_critical_recall']}\n- API latency p50/p95/max ms: {latency['p50_ms']} / {latency['p95_ms']} / {latency['max_ms']}\n- Cost total/page/1000 pages: ${cost['total_usd']:.6f} / ${cost['mean_per_completed_page_usd'] or 0:.6f} / ${cost['projected_per_1000_pages_usd'] or 0:.4f}\n"
    (OUTPUT/"summary.md").write_text(markdown,encoding="utf-8"); print(json.dumps({"model":MODEL,"summary":summary},ensure_ascii=False,sort_keys=True)); return 0 if summary["failed_pages"]==0 else 1


def main() -> int:
    mode=os.environ.get("SCJ_VISUAL_CORPUS_MODE","run")
    if mode=="manifest": build_manifest(); return 0
    if mode=="run": return run_model()
    raise ValueError(f"unknown SCJ_VISUAL_CORPUS_MODE: {mode}")

if __name__=="__main__": raise SystemExit(main())
