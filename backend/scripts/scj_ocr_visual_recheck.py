"""Visual recheck for pages escalated by deterministic/JEV OCR quality review."""

from __future__ import annotations

import argparse
import io
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.gold import score_text_fidelity
from jurisnexo.normalization.visual_reference_ocr import run_tesseract_visual_ocr

PROMPT = (
    "Transcribe every visible word exactly as written. Return only the transcription. "
    "Do not explain, correct spelling, summarize, or infer missing text."
)


def _page_text(page: Any) -> str:
    text_page = page.get_textpage()
    try:
        return text_page.get_text_range()
    finally:
        text_page.close()


def _render(page: Any) -> bytes:
    bitmap = page.render(scale=2.0)
    try:
        image = bitmap.to_pil()
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return stream.getvalue()
    finally:
        bitmap.close()


def _score(expected: str, candidate: str) -> dict[str, object]:
    score = score_text_fidelity(expected_text=expected, candidate_text=candidate)
    return {
        "character_error_rate": score.character_error_rate,
        "word_error_rate": score.word_error_rate,
        "token_content_recall": score.token_content_recall,
        "token_content_precision": score.token_content_precision,
        "token_content_f1": score.token_content_f1,
        "token_order_preservation": score.token_order_preservation,
        "legal_critical_recall": score.legal_critical_recall,
    }


def _load(path: Path, limit: int | None) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise RuntimeError("review candidate is not an object")
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def run(
    *,
    source_pdf: Path,
    input_path: Path,
    output: Path,
    max_cost_usd: float,
    limit: int | None,
) -> int:
    if not 0 < max_cost_usd <= 5.0:
        raise ValueError("max_cost_usd must be > 0 and <= 5.0")
    candidates = _load(input_path, limit)
    output.mkdir(parents=True, exist_ok=True)
    if not candidates:
        (output / "visual-rechecks.jsonl").write_text("", encoding="utf-8")
        (output / "summary.json").write_text(
            json.dumps({"schema_version": 1, "page_count": 0, "cost_usd": 0.0}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return 0

    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for visual recheck")

    provider = OpenRouterVisualModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=models.deepseek_model,
        base_url=settings.base_url,
        reasoning_effort=models.deepseek_reasoning_effort,
        structured_mode="raw_text",
        provider_order=tuple(
            item.strip()
            for item in models.deepseek_provider_order.split(",")
            if item.strip()
        ),
        allow_provider_fallbacks=models.deepseek_allow_provider_fallbacks,
        timeout_seconds=300.0,
    )

    pdf_bytes = source_pdf.read_bytes()
    document = pdfium.PdfDocument(pdf_bytes)
    results: list[dict[str, object]] = []
    total_cost = 0.0
    try:
        for candidate in candidates:
            page_index = int(candidate["page_index"])
            page = document[page_index]
            try:
                native_text = _page_text(page)
                image = _render(page)
            finally:
                page.close()
            ocr = run_tesseract_visual_ocr(
                image,
                language="spa+eng",
                page_segmentation_mode=6,
            )
            started = time.perf_counter()
            response = provider.verify_image_text(
                image=image,
                media_type="image/png",
                prompt=PROMPT,
                json_schema={},
                max_output_tokens=None,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            transcription = str(response.value["transcription"])
            total_cost += response.cost_usd or 0.0
            if total_cost > max_cost_usd:
                raise RuntimeError(
                    f"visual recheck exceeded configured cost cap: {total_cost:.6f} USD"
                )

            native_vlm = _score(native_text, transcription)
            ocr_vlm = _score(ocr.text, transcription)
            native_ocr = _score(native_text, ocr.text)
            if (
                float(native_vlm["word_error_rate"]) <= 0.10
                and float(native_vlm["legal_critical_recall"]) == 1.0
            ):
                consensus = "vlm_supports_native"
            elif (
                float(ocr_vlm["word_error_rate"]) <= 0.10
                and float(ocr_vlm["legal_critical_recall"]) == 1.0
            ):
                consensus = "vlm_supports_tesseract"
            else:
                consensus = "unresolved"

            results.append(
                {
                    "schema_version": 1,
                    "source_pdf_sha256": candidate["source_pdf_sha256"],
                    "page_index": page_index,
                    "prior_classification": candidate.get("classification"),
                    "jev": candidate.get("jev"),
                    "visual_model_requested": models.deepseek_model,
                    "visual_model_returned": response.model,
                    "visual_provider": response.provider,
                    "visual_provider_metadata": response.provider_metadata,
                    "reasoning_effort": models.deepseek_reasoning_effort,
                    "latency_ms": latency_ms,
                    "usage": asdict(response.usage),
                    "cost_usd": response.cost_usd,
                    "native_vs_vlm": native_vlm,
                    "tesseract_vs_vlm": ocr_vlm,
                    "native_vs_tesseract": native_ocr,
                    "consensus": consensus,
                    "transcription": transcription,
                }
            )
    finally:
        document.close()

    (output / "visual-rechecks.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in results),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "page_count": len(results),
        "model_requested": models.deepseek_model,
        "reasoning_effort": models.deepseek_reasoning_effort,
        "cost_usd": total_cost,
        "max_cost_usd": max_cost_usd,
        "consensus_counts": {
            label: sum(item["consensus"] == label for item in results)
            for label in ("vlm_supports_native", "vlm_supports_tesseract", "unresolved")
        },
        "note": (
            "Pairwise consensus is evidence, not primary-source ground truth. "
            "No source or canonical text is overwritten by this stage."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pdf", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cost-usd", type=float, default=0.25)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    return run(
        source_pdf=args.source_pdf,
        input_path=args.input,
        output=args.output,
        max_cost_usd=args.max_cost_usd,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
