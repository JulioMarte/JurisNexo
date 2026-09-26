from __future__ import annotations

import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.visual_identifier_benchmark import (
    VisualIdentifierCase,
    extract_scj_identifier,
    load_visual_identifier_manifest,
    select_visual_identifier_cases,
)

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"),
)
from scj_page_selection import has_native_text, select_reference_page  # noqa: E402

OUTPUT = Path(
    os.environ.get(
        "SCJ_PRINCIPALES_VISUAL_OUTPUT",
        "scj-principales-visual-smoke-output",
    )
)
MODEL = os.environ.get(
    "JURISNEXO_OPENROUTER_VISUAL_MODEL",
    "google/gemini-2.5-flash-lite",
)
MAX_COST_USD = float(
    os.environ.get("SCJ_PRINCIPALES_VISUAL_MAX_COST_USD", "0.005")
)
REASONING = os.environ.get("SCJ_PRINCIPALES_VISUAL_REASONING", "none")
PROVIDER_ORDER = tuple(
    part.strip()
    for part in os.environ.get(
        "JURISNEXO_OPENROUTER_DEEPSEEK_PROVIDER_ORDER",
        "",
    ).split(",")
    if part.strip()
)
SAMPLE_SIZE = int(os.environ.get("SCJ_VISUAL_SAMPLE_SIZE", "1"))
SEED = int(os.environ.get("SCJ_VISUAL_SEED", "20260926"))
SELECTION = os.environ.get("SCJ_VISUAL_SELECTION", "deterministic")
MANIFEST = os.environ.get("SCJ_VISUAL_MANIFEST", "").strip()
MAX_CONCURRENCY = int(os.environ.get("SCJ_VISUAL_MAX_CONCURRENCY", "1"))\nMAX_OUTPUT_TOKENS = int(os.environ.get("SCJ_VISUAL_MAX_OUTPUT_TOKENS", "512"))
PREFIX = "jurisdictions/do/scj/principales-sentencias/"
PROMPT = (
    "Read the image and transcribe the SCJ legal identifier. "
    "Return only the identifier beginning with SCJ-. "
    "No explanation or punctuation outside the identifier."
)


@dataclass(frozen=True, slots=True)
class Result:
    case: VisualIdentifierCase
    observed_text: str
    observed_identifier: str | None
    passed: bool
    model: str
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    routed_provider: str
    error: str | None


def _read_pdf(store: Any, key: str) -> bytes:
    value = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )["Body"].read()
    return value if isinstance(value, bytes) else bytes(value)


def discover_cases(
    store: Any,
    *,
    limit: int = 500,
) -> list[VisualIdentifierCase]:
    response = store.client.list_objects_v2(
        Bucket=store.config.bucket,
        Prefix=PREFIX,
        MaxKeys=min(1000, max(limit * 4, 100)),
    )
    cases: list[VisualIdentifierCase] = []
    keys = sorted(
        str(item.get("Key") or "")
        for item in response.get("Contents", [])
        if str(item.get("Key") or "").endswith(".pdf")
    )
    for key in keys:
        source = _read_pdf(store, key)
        if not has_native_text(source):
            continue
        page = select_reference_page(
            source,
            min_reference_chars=800,
            max_pages_to_scan=120,
        )
        if page is None:
            continue
        expected = extract_scj_identifier(page.text)
        if expected is None:
            continue
        cases.append(
            VisualIdentifierCase(
                object_key=key,
                page_index=page.page_index,
                expected_identifier=expected,
                gold_source="pdf_text_layer",
            )
        )
        if len(cases) >= limit:
            break
    return cases


def _page_text_boxes(
    pdf_bytes: bytes,
    page_index: int,
) -> tuple[
    str,
    list[tuple[float, float, float, float]],
    float,
    float,
]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            width, height = page.get_size()
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_range()
                boxes = [
                    tuple(
                        float(value)
                        for value in text_page.get_charbox(index)
                    )
                    for index in range(len(text))
                ]
            finally:
                text_page.close()
            return text, boxes, float(width), float(height)
        finally:
            page.close()
    finally:
        document.close()


def render_crop(
    pdf_bytes: bytes,
    page_index: int,
    token: str,
) -> bytes:
    import pypdfium2 as pdfium

    text, boxes, width, height = _page_text_boxes(
        pdf_bytes,
        page_index,
    )
    start = text.casefold().find(token.casefold())
    if start < 0:
        raise RuntimeError(
            f"gold identifier absent from text layer: {token}"
        )
    target_boxes = boxes[start : start + len(token)]
    left = min(box[0] for box in target_boxes)
    bottom = min(box[1] for box in target_boxes)
    right = max(box[2] for box in target_boxes)
    top = max(box[3] for box in target_boxes)
    horizontal_margin = max(80.0, (right - left) * 1.5)
    vertical_margin = max(36.0, (top - bottom) * 4.0)
    crop = (
        max(0.0, left - horizontal_margin),
        max(0.0, bottom - vertical_margin),
        max(0.0, width - right - horizontal_margin),
        max(0.0, height - top - vertical_margin),
    )

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=3.0, crop=crop)
            try:
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _provider() -> OpenRouterVisualModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return OpenRouterVisualModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=MODEL,
        base_url=settings.base_url,
        reasoning_effort=REASONING,
        structured_mode="raw_text",
        provider_order=PROVIDER_ORDER,
        allow_provider_fallbacks=not bool(PROVIDER_ORDER),
    )


def _run_case(
    provider: OpenRouterVisualModelProvider,
    case: VisualIdentifierCase,
    image: bytes,
) -> Result:
    started = time.perf_counter()
    try:
        response = provider.verify_image_text(
            image=image,
            media_type="image/png",
            prompt=PROMPT,
            json_schema={"type": "object"},
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        raw = str(response.value.get("transcription") or "").strip()
        observed = extract_scj_identifier(raw)
        return Result(
            case=case,
            observed_text=raw,
            observed_identifier=observed,
            passed=observed == case.expected_identifier,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=response.usage.thinking_tokens,
            cost_usd=response.cost_usd,
            latency_ms=int((time.perf_counter() - started) * 1000),
            routed_provider=str(
                response.provider_metadata.get("routed_provider") or ""
            ),
            error=None,
        )
    except ModelProviderError as exc:
        return Result(
            case=case,
            observed_text="",
            observed_identifier=None,
            passed=False,
            model=MODEL,
            input_tokens=None,
            output_tokens=None,
            thinking_tokens=None,
            cost_usd=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            routed_provider="",
            error=str(exc),
        )


def main() -> int:
    if not 0 < MAX_COST_USD <= 1:
        raise ValueError("invalid aggregate cost cap")
    if SAMPLE_SIZE < 1:
        raise ValueError("SCJ_VISUAL_SAMPLE_SIZE must be >= 1")
    if not 1 <= MAX_CONCURRENCY <= SAMPLE_SIZE:
        raise ValueError(
            "SCJ_VISUAL_MAX_CONCURRENCY must be between 1 and sample size"
        )

    store = build_s3_object_store()
    pool = (
        load_visual_identifier_manifest(MANIFEST)
        if MANIFEST
        else discover_cases(store, limit=max(500, SAMPLE_SIZE))
    )
    cases = select_visual_identifier_cases(
        pool,
        sample_size=SAMPLE_SIZE,
        selection=SELECTION,
        seed=SEED,
    )

    prepared: list[tuple[VisualIdentifierCase, bytes]] = []
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(cases):
        pdf_bytes = _read_pdf(store, case.object_key)
        image = render_crop(
            pdf_bytes,
            case.page_index,
            case.expected_identifier,
        )
        (OUTPUT / f"case-{index:04d}.png").write_bytes(image)
        prepared.append((case, image))

    provider = _provider()
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_to_case = {
            executor.submit(_run_case, provider, case, image): case
            for case, image in prepared
        }
        for future in as_completed(future_to_case):
            results.append(future.result())

    results.sort(
        key=lambda result: (
            result.case.object_key,
            result.case.page_index,
        )
    )
    total_cost = sum(result.cost_usd or 0.0 for result in results)
    if total_cost > MAX_COST_USD:
        raise RuntimeError(
            f"aggregate visual benchmark cost ${total_cost:.6f} "
            f"exceeded ${MAX_COST_USD:.6f}"
        )

    passed = sum(result.passed for result in results)
    latencies = [result.latency_ms for result in results]
    payload = {
        "schema_version": 7,
        "benchmark_kind": "visual_identifier_transcription",
        "selection": {
            "mode": SELECTION,
            "seed": SEED,
            "sample_size": SAMPLE_SIZE,
            "manifest": MANIFEST or None,
        },
        "model": MODEL,
        "reasoning_effort": REASONING,
        "max_concurrency": MAX_CONCURRENCY,\n        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "accuracy": passed / len(results),
        "observed_cost_usd": total_cost,
        "mean_cost_per_case_usd": total_cost / len(results),
        "latency_ms": {
            "mean": sum(latencies) / len(latencies),
            "min": min(latencies),
            "max": max(latencies),
        },
        "results": [asdict(result) for result in results],
    }
    (OUTPUT / "results.json").write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
