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
from jurisnexo.model_providers.openrouter_visual import (
    OpenRouterVisualModelProvider,
)

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
PREFIX = "jurisdictions/do/scj/principales-sentencias/"


@dataclass(frozen=True, slots=True)
class VisualCaseResult:
    case: str
    expected_matches: bool
    observed_matches: bool
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    material_differences: tuple[str, ...]


def _first_suitable_source(
    store: Any,
) -> tuple[str, bytes, int, str]:
    """Return the first Principales volume with a real judgment body page.

    Front matter (cover, credits, ISBN, catalog card, table of contents) has no
    corruptible legal token and is not legal-document text, so it is skipped.
    """

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
        return object_key, source, selected.page_index, selected.text
    raise RuntimeError("no Principales volume exposed a native-text judgment page")


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _corrupt_legal_token(text: str) -> str:
    patterns = (
        re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE),
        re.compile(r"\b\d{3,}\b"),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match is None:
            continue
        token = match.group(0)
        chars = list(token)
        for index in range(len(chars) - 1, -1, -1):
            if chars[index].isdigit():
                chars[index] = "9" if chars[index] != "9" else "8"
                replacement = "".join(chars)
                return text[: match.start()] + replacement + text[match.end() :]
    raise RuntimeError("could not find a deterministic legal token to corrupt")


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "corrected_text": {"type": ["string", "null"]},
            "material_differences": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 6,
            },
        },
        "required": ["matches", "corrected_text", "material_differences"],
        "additionalProperties": False,
    }


def _run_case(
    *,
    provider: OpenRouterVisualModelProvider,
    image: bytes,
    candidate: str,
    case_name: str,
    expected_matches: bool,
) -> VisualCaseResult:
    started = time.perf_counter()
    result = provider.verify_image_text(
        image=image,
        media_type="image/png",
        prompt=(
            "Compare the visible legal text in this page image against the candidate "
            "transcription. Judge literal transcription fidelity only. Do not infer "
            "legal conclusions. A changed case number, date, amount, article number, "
            "law number, party name, or dispositive wording is material. Return "
            "matches=true only when there is no material visible difference.\n\n"
            f"Candidate transcription:\n{candidate}"
        ),
        json_schema=_schema(),
        max_output_tokens=800,
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
    )


def main() -> int:
    if MAX_COST_USD <= 0 or MAX_COST_USD > 0.01:
        raise ValueError("visual smoke cost cap must be > 0 and <= 0.01")

    openrouter = get_openrouter_settings()
    models = get_normalization_model_settings()
    if openrouter.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for visual smoke")

    store = build_s3_object_store()
    object_key, source, page_index, native_text = _first_suitable_source(store)
    image = _render_page(source, page_index)
    candidate = native_text[:2500]
    corrupted = _corrupt_legal_token(candidate)

    provider = OpenRouterVisualModelProvider(
        api_key=openrouter.api_key.get_secret_value(),
        model=MODEL,
        base_url=openrouter.base_url,
        reasoning_effort=models.deepseek_reasoning_effort,
    )

    good = _run_case(
        provider=provider,
        image=image,
        candidate=candidate,
        case_name="native_candidate",
        expected_matches=True,
    )
    running_cost = good.cost_usd or 0.0
    if running_cost > MAX_COST_USD:
        raise RuntimeError(
            f"visual smoke exceeded cost cap after first call: ${running_cost:.6f}"
        )

    corrupted_result = _run_case(
        provider=provider,
        image=image,
        candidate=corrupted,
        case_name="controlled_critical_corruption",
        expected_matches=False,
    )
    running_cost += corrupted_result.cost_usd or 0.0
    if running_cost > MAX_COST_USD:
        raise RuntimeError(
            f"visual smoke exceeded cost cap: ${running_cost:.6f}"
        )

    cases = (good, corrupted_result)
    false_correction_rate = (
        sum(
            result.expected_matches and not result.observed_matches
            for result in cases
        )
        / sum(result.expected_matches for result in cases)
    )
    corruption_detection_recall = (
        sum(
            (not result.expected_matches) and (not result.observed_matches)
            for result in cases
        )
        / sum(not result.expected_matches for result in cases)
    )
    payload = {
        "schema_version": 1,
        "source": "scj",
        "collection": "principales-sentencias",
        "object_key": object_key,
        "page_index": page_index,
        "model": MODEL,
        "reasoning_effort": models.deepseek_reasoning_effort,
        "model_call_count": 2,
        "observed_cost_usd": running_cost,
        "max_cost_usd": MAX_COST_USD,
        "false_correction_rate": false_correction_rate,
        "corruption_detection_recall": corruption_detection_recall,
        "cases": [asdict(item) for item in cases],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return (
        0
        if false_correction_rate == 0.0
        and corruption_detection_recall == 1.0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
