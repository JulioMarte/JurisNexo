from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"),
)
from scj_page_selection import (  # noqa: E402
    has_native_text,
    select_reference_page,
)

OUTPUT = Path(
    os.environ.get(
        "SCJ_PRINCIPALES_VISUAL_OUTPUT",
        "scj-principales-visual-smoke-output",
    )
)
MODEL = os.environ.get(
    "JURISNEXO_OPENROUTER_VISUAL_MODEL",
    "deepseek/deepseek-v4.1-flash",
)
MAX_COST_USD = float(
    os.environ.get("SCJ_PRINCIPALES_VISUAL_MAX_COST_USD", "0.005")
)
VISUAL_REASONING = os.environ.get("SCJ_PRINCIPALES_VISUAL_REASONING", "none")
PREFIX = "jurisdictions/do/scj/principales-sentencias/"


@dataclass(frozen=True, slots=True)
class VisualTarget:
    original_token: str
    corrupted_token: str
    start: int
    end: int
    context_start: int
    context_end: int


@dataclass(frozen=True, slots=True)
class VisualCaseResult:
    case: str
    expected_matches: bool | None
    observed_matches: bool
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    material_differences: tuple[str, ...]
    routed_provider: str
    structured_mode: str


def _first_suitable_source(
    store: Any,
) -> tuple[str, bytes, int, str]:
    response = store.client.list_objects_v2(
        Bucket=store.config.bucket,
        Prefix=PREFIX,
        MaxKeys=100,
    )
    keys = sorted(
        str(item.get("Key") or "")
        for item in response.get("Contents", [])
        if str(item.get("Key") or "").endswith(".pdf")
    )
    if not keys:
        raise RuntimeError("no SCJ Principales PDF found in object storage")
    for object_key in keys:
        source = store.client.get_object(
            Bucket=store.config.bucket,
            Key=object_key,
        )["Body"].read()
        if not isinstance(source, bytes):
            source = bytes(source)
        if not has_native_text(source):
            continue
        selected = select_reference_page(
            source,
            min_reference_chars=800,
            max_pages_to_scan=120,
        )
        if selected is None:
            continue
        try:
            _find_visual_target(selected.text)
        except RuntimeError:
            continue
        return object_key, source, selected.page_index, selected.text
    raise RuntimeError(
        "no Principales judgment page exposed a targetable legal identifier"
    )


def _find_visual_target(text: str) -> VisualTarget:
    patterns = (
        re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE),
        re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){2,}\b", re.IGNORECASE),
        re.compile(r"\b\d{3,}\b"),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match is None:
            continue
        token = match.group(0)
        chars = list(token)
        for index in range(len(chars) - 1, -1, -1):
            if not chars[index].isdigit():
                continue
            chars[index] = "9" if chars[index] != "9" else "8"
            context_start = max(0, match.start() - 140)
            context_end = min(len(text), match.end() + 140)
            return VisualTarget(
                original_token=token,
                corrupted_token="".join(chars),
                start=match.start(),
                end=match.end(),
                context_start=context_start,
                context_end=context_end,
            )
    raise RuntimeError("could not find a deterministic legal token to corrupt")


def _page_text_and_charboxes(
    pdf_bytes: bytes,
    page_index: int,
) -> tuple[str, list[tuple[float, float, float, float]], float, float]:
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
                    tuple(float(value) for value in text_page.get_charbox(index))
                    for index in range(len(text))
                ]
            finally:
                text_page.close()
            return text, boxes, float(width), float(height)
        finally:
            page.close()
    finally:
        document.close()


def _find_token_span(page_text: str, token: str) -> tuple[int, int]:
    index = page_text.casefold().find(token.casefold())
    if index < 0:
        compact_page = re.sub(r"\s+", " ", page_text)
        compact_token = re.sub(r"\s+", " ", token)
        compact_index = compact_page.casefold().find(compact_token.casefold())
        if compact_index >= 0:
            raise RuntimeError(
                "target token is visible only after whitespace normalization; "
                "cannot map it safely to character boxes"
            )
        raise RuntimeError(f"target token not found in PDF text layer: {token!r}")
    return index, index + len(token)


def _render_target_crop(
    pdf_bytes: bytes,
    page_index: int,
    *,
    token: str,
) -> bytes:
    import pypdfium2 as pdfium

    page_text, boxes, width, height = _page_text_and_charboxes(
        pdf_bytes, page_index
    )
    start, end = _find_token_span(page_text, token)
    target_boxes = boxes[start:end]
    if not target_boxes:
        raise RuntimeError("target token produced no character boxes")

    left = min(box[0] for box in target_boxes)
    bottom = min(box[1] for box in target_boxes)
    right = max(box[2] for box in target_boxes)
    top = max(box[3] for box in target_boxes)

    horizontal_margin = max(80.0, (right - left) * 1.5)
    vertical_margin = max(36.0, (top - bottom) * 4.0)
    crop = (
        max(0.0, left - horizontal_margin),
        max(0.0, bottom - vertical_margin),
        max(0.0, width - (right + horizontal_margin)),
        max(0.0, height - (top + vertical_margin)),
    )

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=3.0, crop=crop)
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "corrected_text": {"type": ["string", "null"]},
            "material_differences": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 4,
            },
        },
        "required": ["matches", "corrected_text", "material_differences"],
        "additionalProperties": False,
    }


def _run_case(
    *,
    provider: OpenRouterVisualModelProvider,
    image: bytes,
    candidate_context: str,
    target_token: str,
    case_name: str,
    expected_matches: bool | None,
) -> VisualCaseResult:
    started = time.perf_counter()
    result = provider.verify_image_text(
        image=image,
        media_type="image/png",
        prompt=(
            "This image is a localized crop around one legal identifier. "
            "Compare the exact visible identifier against TARGET_TOKEN. "
            "Ignore differences elsewhere in the surrounding context, capitalization "
            "outside the token, and layout. Return matches=true only if the visible "
            "identifier exactly matches TARGET_TOKEN. If it differs, return "
            "matches=false and put the visible identifier in corrected_text.\n\n"
            f"TARGET_TOKEN: {target_token}\n\n"
            f"Nearby candidate context:\n{candidate_context}"
        ),
        json_schema=_schema(),
        # Reasoning-capable providers count hidden reasoning against the completion
        # budget. 300 tokens was enough for the clean case but truncated the final
        # JSON on the controlled corruption. Keep the task bounded while leaving
        # enough room for hidden reasoning plus the tiny final object.
        max_output_tokens=1200,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    raw_differences = result.value.get("material_differences", [])
    differences = (
        tuple(str(item) for item in raw_differences)
        if isinstance(raw_differences, list)
        else ()
    )
    return VisualCaseResult(
        case=case_name,
        expected_matches=expected_matches,
        observed_matches=bool(result.value.get("matches", False)),
        model=result.model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=result.cost_usd,
        latency_ms=latency_ms,
        material_differences=differences,
        routed_provider=str(result.provider_metadata.get("routed_provider") or ""),
        structured_mode=str(result.provider_metadata.get("structured_mode") or ""),
    )


def main() -> int:
    if MAX_COST_USD <= 0 or MAX_COST_USD > 0.01:
        raise ValueError("visual smoke cost cap must be > 0 and <= 0.01")

    openrouter = get_openrouter_settings()
    if openrouter.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for visual smoke")

    models = get_normalization_model_settings()
    provider_order = tuple(
        part.strip()
        for part in models.deepseek_provider_order.split(",")
        if part.strip()
    )
    store = build_s3_object_store()
    object_key, source, page_index, native_text = _first_suitable_source(store)
    target = _find_visual_target(native_text)
    image = _render_target_crop(
        source,
        page_index,
        token=target.original_token,
    )
    clean_context = native_text[target.context_start : target.context_end]
    relative_start = target.start - target.context_start
    relative_end = target.end - target.context_start
    corrupted_context = (
        clean_context[:relative_start]
        + target.corrupted_token
        + clean_context[relative_end:]
    )

    provider = OpenRouterVisualModelProvider(
        api_key=openrouter.api_key.get_secret_value(),
        model=MODEL,
        base_url=openrouter.base_url,
        reasoning_effort=VISUAL_REASONING,
        structured_mode=models.deepseek_structured_mode,
        provider_order=provider_order,
        allow_provider_fallbacks=models.deepseek_allow_provider_fallbacks,
    )

    good: VisualCaseResult | None = None
    corrupted_result: VisualCaseResult | None = None
    provider_errors: list[str] = []
    running_cost = 0.0

    try:
        good = _run_case(
            provider=provider,
            image=image,
            candidate_context=clean_context,
            target_token=target.original_token,
            case_name="native_reference_audit",
            expected_matches=None,
        )
        running_cost += good.cost_usd or 0.0
    except ModelProviderError as exc:
        provider_errors.append(f"native_reference_audit: {exc}")

    if running_cost > MAX_COST_USD:
        raise RuntimeError(
            f"visual smoke exceeded cost cap after first call: ${running_cost:.6f}"
        )

    try:
        corrupted_result = _run_case(
            provider=provider,
            image=image,
            candidate_context=corrupted_context,
            target_token=target.corrupted_token,
            case_name="controlled_critical_corruption",
            expected_matches=False,
        )
        running_cost += corrupted_result.cost_usd or 0.0
    except ModelProviderError as exc:
        provider_errors.append(f"controlled_critical_corruption: {exc}")

    if running_cost > MAX_COST_USD:
        raise RuntimeError(
            f"visual smoke exceeded cost cap: ${running_cost:.6f}"
        )

    cases = tuple(case for case in (good, corrupted_result) if case is not None)
    verified_clean_cases = tuple(
        result for result in cases if result.expected_matches is True
    )
    corrupted_cases = tuple(
        result for result in cases if result.expected_matches is False
    )
    false_correction_rate = (
        sum(not result.observed_matches for result in verified_clean_cases)
        / len(verified_clean_cases)
        if verified_clean_cases
        else None
    )
    corruption_detection_recall = (
        sum(not result.observed_matches for result in corrupted_cases)
        / len(corrupted_cases)
        if corrupted_cases
        else None
    )
    reference_audit_found_difference = any(
        result.expected_matches is None and not result.observed_matches
        for result in cases
    )
    promotion_blockers = ["no_human_verified_clean_visual_gold"]
    smoke_passed = not provider_errors and corruption_detection_recall == 1.0

    payload = {
        "schema_version": 4,
        "source": "scj",
        "collection": "principales-sentencias",
        "runtime_status": (
            "ok" if not provider_errors else "provider_structured_output_failed"
        ),
        "provider_errors": provider_errors,
        "object_key": object_key,
        "page_index": page_index,
        "verification_scope": "localized_legal_identifier_crop",
        "target_original_token": target.original_token,
        "target_corrupted_token": target.corrupted_token,
        "candidate_context_characters": len(clean_context),
        "reference_kind": "native_pdf_text_unverified_against_image",
        "model": MODEL,
        "reasoning_effort": VISUAL_REASONING,
        "structured_mode": models.deepseek_structured_mode,
        "provider_order": list(provider_order),
        "allow_provider_fallbacks": models.deepseek_allow_provider_fallbacks,
        "model_call_count": len(cases),
        "observed_cost_usd": running_cost,
        "max_cost_usd": MAX_COST_USD,
        "false_correction_rate": false_correction_rate,
        "corruption_detection_recall": corruption_detection_recall,
        "reference_audit_found_difference": reference_audit_found_difference,
        "human_verified_clean_case_count": len(verified_clean_cases),
        "promotion_eligible": False,
        "promotion_blockers": promotion_blockers,
        "smoke_passed": smoke_passed,
        "cases": [asdict(item) for item in cases],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "target-crop.png").write_bytes(image)
    (OUTPUT / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())