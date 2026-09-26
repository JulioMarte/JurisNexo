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
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"))
from scj_page_selection import has_native_text, select_reference_page  # noqa: E402

OUTPUT = Path(os.environ.get("SCJ_PRINCIPALES_VISUAL_OUTPUT", "scj-principales-visual-smoke-output"))
MODEL = os.environ.get("JURISNEXO_OPENROUTER_VISUAL_MODEL", "deepseek/deepseek-v4.1-flash")
MAX_COST_USD = float(os.environ.get("SCJ_PRINCIPALES_VISUAL_MAX_COST_USD", "0.005"))
VISUAL_REASONING = os.environ.get("SCJ_PRINCIPALES_VISUAL_REASONING", "none")
PROVIDER_ORDER = tuple(part.strip() for part in os.environ.get("JURISNEXO_OPENROUTER_DEEPSEEK_PROVIDER_ORDER", "").split(",") if part.strip())
PREFIX = "jurisdictions/do/scj/principales-sentencias/"
PROMPT = "Transcribe exactly the legal identifier visible in this image. Return only the identifier itself. Do not explain, correct, normalize, compare, add Markdown, or add any other text."

@dataclass(frozen=True, slots=True)
class VisualTarget:
    original_token: str

@dataclass(frozen=True, slots=True)
class VisualResult:
    expected_text: str
    observed_text: str
    exact_match: bool
    model: str
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    routed_provider: str

def _find_visual_target(text: str) -> VisualTarget:
    for pattern in (re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE), re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]{2,}){2,}\b", re.IGNORECASE)):
        match = pattern.search(text)
        if match is not None:
            return VisualTarget(match.group(0))
    raise RuntimeError("could not find a deterministic legal identifier")

def _first_suitable_source(store: Any) -> tuple[str, bytes, int, str]:
    response = store.client.list_objects_v2(Bucket=store.config.bucket, Prefix=PREFIX, MaxKeys=100)
    keys = sorted(str(item.get("Key") or "") for item in response.get("Contents", []) if str(item.get("Key") or "").endswith(".pdf"))
    if not keys:
        raise RuntimeError("no SCJ Principales PDF found in object storage")
    for object_key in keys:
        source = store.client.get_object(Bucket=store.config.bucket, Key=object_key)["Body"].read()
        if not isinstance(source, bytes): source = bytes(source)
        if not has_native_text(source): continue
        selected = select_reference_page(source, min_reference_chars=800, max_pages_to_scan=120)
        if selected is None: continue
        try: _find_visual_target(selected.text)
        except RuntimeError: continue
        return object_key, source, selected.page_index, selected.text
    raise RuntimeError("no Principales judgment page exposed a targetable legal identifier")

def _page_text_and_charboxes(pdf_bytes: bytes, page_index: int) -> tuple[str, list[tuple[float, float, float, float]], float, float]:
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            width, height = page.get_size(); text_page = page.get_textpage()
            try:
                text = text_page.get_text_range(); boxes = [tuple(float(v) for v in text_page.get_charbox(i)) for i in range(len(text))]
            finally: text_page.close()
            return text, boxes, float(width), float(height)
        finally: page.close()
    finally: document.close()

def _render_target_crop(pdf_bytes: bytes, page_index: int, *, token: str) -> bytes:
    import pypdfium2 as pdfium
    page_text, boxes, width, height = _page_text_and_charboxes(pdf_bytes, page_index)
    start = page_text.casefold().find(token.casefold())
    if start < 0: raise RuntimeError(f"target identifier not found in PDF text layer: {token!r}")
    target_boxes = boxes[start:start + len(token)]
    left=min(b[0] for b in target_boxes); bottom=min(b[1] for b in target_boxes); right=max(b[2] for b in target_boxes); top=max(b[3] for b in target_boxes)
    hm=max(80.0,(right-left)*1.5); vm=max(36.0,(top-bottom)*4.0)
    crop=(max(0.0,left-hm),max(0.0,bottom-vm),max(0.0,width-(right+hm)),max(0.0,height-(top+vm)))
    document=pdfium.PdfDocument(pdf_bytes)
    try:
        page=document[page_index]
        try:
            image=page.render(scale=3.0,crop=crop).to_pil(); output=io.BytesIO(); image.save(output,format="PNG"); return output.getvalue()
        finally: page.close()
    finally: document.close()

def main() -> int:
    if MAX_COST_USD <= 0 or MAX_COST_USD > 0.01: raise ValueError("visual smoke cost cap must be > 0 and <= 0.01")
    openrouter=get_openrouter_settings()
    if openrouter.api_key is None: raise RuntimeError("OPENROUTER_API_KEY is required for visual smoke")
    store=build_s3_object_store(); object_key,source,page_index,native_text=_first_suitable_source(store); target=_find_visual_target(native_text); image=_render_target_crop(source,page_index,token=target.original_token)
    provider=OpenRouterVisualModelProvider(api_key=openrouter.api_key.get_secret_value(),model=MODEL,base_url=openrouter.base_url,reasoning_effort=VISUAL_REASONING,structured_mode="raw_text",provider_order=PROVIDER_ORDER,allow_provider_fallbacks=False)
    result=None; provider_errors=[]; started=time.perf_counter()
    try:
        response=provider.verify_image_text(image=image,media_type="image/png",prompt=PROMPT,json_schema={"type":"object"},max_output_tokens=300)
        observed=str(response.value.get("transcription") or "").strip()
        result=VisualResult(target.original_token,observed,observed==target.original_token,response.model,response.usage.input_tokens,response.usage.output_tokens,response.usage.thinking_tokens,response.cost_usd,int((time.perf_counter()-started)*1000),str(response.provider_metadata.get("routed_provider") or ""))
    except ModelProviderError as exc: provider_errors.append(str(exc))
    observed_cost=(result.cost_usd or 0.0) if result is not None else 0.0
    if observed_cost > MAX_COST_USD: raise RuntimeError(f"visual smoke exceeded cost cap: ${observed_cost:.6f}")
    smoke_passed=not provider_errors and result is not None and result.exact_match
    payload={"schema_version":5,"source":"scj","collection":"principales-sentencias","benchmark_kind":"blind_visual_identifier_transcription","object_key":object_key,"page_index":page_index,"model":MODEL,"reasoning_effort":VISUAL_REASONING,"structured_mode":"raw_text","provider_order":list(PROVIDER_ORDER),"model_call_count":1 if result is not None else 0,"observed_cost_usd":observed_cost,"max_cost_usd":MAX_COST_USD,"provider_errors":provider_errors,"smoke_passed":smoke_passed,"result":asdict(result) if result is not None else None}
    OUTPUT.mkdir(parents=True,exist_ok=True); (OUTPUT/"target-crop.png").write_bytes(image); (OUTPUT/"results.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)); return 0 if smoke_passed else 1

if __name__ == "__main__": raise SystemExit(main())
