from __future__ import annotations

import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
PAGE_LIMIT = int(os.environ.get("VISUAL_JUDGE_PAGE_LIMIT", "1"))
OUTPUT = Path(os.environ.get("VISUAL_JUDGE_OUTPUT", "visual-judge-100-page-output"))
MAX_COST_USD = float(os.environ.get("VISUAL_JUDGE_MAX_COST_USD", "1.0"))
MODEL = os.environ["VISUAL_JUDGE_MODEL"]
PROVIDER = os.environ["VISUAL_JUDGE_PROVIDER"]
REASONING = os.environ.get("VISUAL_JUDGE_REASONING", "high")
STRUCTURED_MODE = os.environ.get("VISUAL_JUDGE_STRUCTURED_MODE", "tool")
MAX_OUTPUT_TOKENS = int(os.environ.get("VISUAL_JUDGE_MAX_OUTPUT_TOKENS", "512"))

TOKEN_PATTERNS = (
    re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){2,}\b", re.IGNORECASE),
    re.compile(r"\b\d{4,}\b"),
)


@dataclass(frozen=True, slots=True)
class PageCase:
    object_key: str
    page_index: int
    case_kind: str
    original_token: str
    candidate_token: str
    expected_matches: bool


@dataclass(frozen=True, slots=True)
class PageResult:
    object_key: str
    page_index: int
    case_kind: str
    expected_matches: bool
    observed_matches: bool
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    routed_provider: str


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "visible_token": {"type": ["string", "null"]},
        },
        "required": ["matches", "visible_token"],
        "additionalProperties": False,
    }


def _target(text: str) -> tuple[str, str] | None:
    for pattern in TOKEN_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        token = match.group(0)
        chars = list(token)
        for index in range(len(chars) - 1, -1, -1):
            if chars[index].isdigit():
                chars[index] = "9" if chars[index] != "9" else "8"
                return token, "".join(chars)
    return None


def _page_text(document: pdfium.PdfDocument, page_index: int) -> str:
    page = document[page_index]
    try:
        text_page = page.get_textpage()
        try:
            return text_page.get_text_range().strip()
        finally:
            text_page.close()
    finally:
        page.close()


def _render_page(document: pdfium.PdfDocument, page_index: int) -> bytes:
    page = document[page_index]
    try:
        bitmap = page.render(scale=2.0)
        image = bitmap.to_pil().convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()
    finally:
        page.close()


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
            break
    return sorted(set(keys))


def _candidate_pages(store: Any) -> list[tuple[PageCase, bytes]]:
    selected: list[tuple[PageCase, bytes]] = []
    for object_key in _list_pdf_keys(store):
        source = store.client.get_object(
            Bucket=store.config.bucket, Key=object_key
        )["Body"].read()
        if not isinstance(source, bytes):
            source = bytes(source)
        try:
            document = pdfium.PdfDocument(source)
        except Exception:
            continue
        try:
            page_count = len(document)
            if page_count == 0:
                continue
            stride = max(1, page_count // 12)
            for page_index in range(0, page_count, stride):
                text = _page_text(document, page_index)
                if len(text) < 800:
                    continue
                target = _target(text)
                if target is None:
                    continue
                original, corrupted = target
                expected_matches = len(selected) % 2 == 0
                candidate = original if expected_matches else corrupted
                image = _render_page(document, page_index)
                selected.append(
                    (
                        PageCase(
                            object_key=object_key,
                            page_index=page_index,
                            case_kind="clean" if expected_matches else "controlled_corruption",
                            original_token=original,
                            candidate_token=candidate,
                            expected_matches=expected_matches,
                        ),
                        image,
                    )
                )
                if len(selected) >= PAGE_LIMIT:
                    return selected
        finally:
            document.close()
    return selected


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> int:
    if PAGE_LIMIT <= 0 or PAGE_LIMIT > 100:
        raise ValueError("VISUAL_JUDGE_PAGE_LIMIT must be between 1 and 100")
    if MAX_COST_USD <= 0 or MAX_COST_USD > 2:
        raise ValueError("VISUAL_JUDGE_MAX_COST_USD must be >0 and <=2")
    if STRUCTURED_MODE not in {"tool", "json_schema", "json_object"}:
        raise ValueError("unsupported VISUAL_JUDGE_STRUCTURED_MODE")
    if MAX_OUTPUT_TOKENS < 64 or MAX_OUTPUT_TOKENS > 4096:
        raise ValueError("VISUAL_JUDGE_MAX_OUTPUT_TOKENS must be between 64 and 4096")
    openrouter = get_openrouter_settings()
    if openrouter.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    store = build_s3_object_store()
    pages = _candidate_pages(store)
    if len(pages) != PAGE_LIMIT:
        raise RuntimeError(f"requested {PAGE_LIMIT} pages but found {len(pages)} eligible pages")

    provider = OpenRouterVisualModelProvider(
        api_key=openrouter.api_key.get_secret_value(),
        model=MODEL,
        base_url=openrouter.base_url,
        reasoning_effort=REASONING,
        structured_mode=STRUCTURED_MODE,
        provider_order=(PROVIDER,),
        allow_provider_fallbacks=False,
    )
    results: list[PageResult] = []
    running_cost = 0.0
    for case, image in pages:
        started = time.perf_counter()
        result = provider.verify_image_text(
            image=image,
            media_type="image/jpeg",
            prompt=(
                "Read the full legal-document page image. Locate the exact visible legal "
                "identifier represented by CANDIDATE_TOKEN. Return matches=true only when "
                "the visible token is exactly identical, character for character. Do not "
                "infer or repair from context. If it differs, return matches=false and the "
                "visible token.\n\nCANDIDATE_TOKEN: " + case.candidate_token
            ),
            json_schema=_schema(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        running_cost += result.cost_usd or 0.0
        if running_cost > MAX_COST_USD:
            raise RuntimeError(f"benchmark exceeded cost cap: ${running_cost:.6f}")
        results.append(
            PageResult(
                object_key=case.object_key,
                page_index=case.page_index,
                case_kind=case.case_kind,
                expected_matches=case.expected_matches,
                observed_matches=bool(result.value.get("matches", False)),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                thinking_tokens=result.usage.thinking_tokens,
                cost_usd=result.cost_usd,
                latency_ms=int((time.perf_counter() - started) * 1000),
                routed_provider=str(result.provider_metadata.get("routed_provider") or ""),
            )
        )

    clean = [item for item in results if item.expected_matches]
    corrupted = [item for item in results if not item.expected_matches]
    false_corrections = sum(not item.observed_matches for item in clean)
    detected_corruptions = sum(not item.observed_matches for item in corrupted)
    costs = [item.cost_usd for item in results if item.cost_usd is not None]
    latencies = [item.latency_ms for item in results]
    payload = {
        "schema_version": 1,
        "model": MODEL,
        "pinned_provider": PROVIDER,
        "structured_mode": STRUCTURED_MODE,
        "reasoning_effort": REASONING,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "page_count": len(results),
        "clean_page_count": len(clean),
        "controlled_corruption_count": len(corrupted),
        "false_correction_rate": _rate(false_corrections, len(clean)),
        "corruption_detection_recall": _rate(detected_corruptions, len(corrupted)),
        "observed_cost_usd": running_cost,
        "mean_cost_per_page_usd": (sum(costs) / len(costs)) if costs else None,
        "mean_latency_ms": sum(latencies) / len(latencies),
        "input_tokens": sum(item.input_tokens or 0 for item in results),
        "output_tokens": sum(item.output_tokens or 0 for item in results),
        "thinking_tokens": sum(item.thinking_tokens or 0 for item in results),
        "results": [asdict(item) for item in results],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
