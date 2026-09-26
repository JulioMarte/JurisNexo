from __future__ import annotations

import io, json, os, sys, time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"))
from scj_page_selection import has_native_text, select_reference_page  # noqa: E402

OUTPUT=Path(os.environ.get("SCJ_PRINCIPALES_VISUAL_OUTPUT","scj-principales-visual-smoke-output"))
MODEL=os.environ.get("JURISNEXO_OPENROUTER_VISUAL_MODEL","google/gemini-2.5-flash-lite")
MAX_COST_USD=float(os.environ.get("SCJ_PRINCIPALES_VISUAL_MAX_COST_USD","0.005"))
REASONING=os.environ.get("SCJ_PRINCIPALES_VISUAL_REASONING","none")
PROVIDER_ORDER=tuple(x.strip() for x in os.environ.get("JURISNEXO_OPENROUTER_DEEPSEEK_PROVIDER_ORDER","").split(",") if x.strip())
SAMPLE_SIZE=int(os.environ.get("SCJ_VISUAL_SAMPLE_SIZE","1")); SEED=int(os.environ.get("SCJ_VISUAL_SEED","20260926"))
SELECTION=os.environ.get("SCJ_VISUAL_SELECTION","deterministic")
MANIFEST=os.environ.get("SCJ_VISUAL_MANIFEST","").strip()
PREFIX="jurisdictions/do/scj/principales-sentencias/"
IDENTIFIER=re.compile(r"SCJ-[A-Z0-9-]{4,}",re.I)
PROMPT="Read the image and transcribe the SCJ legal identifier. Return only the identifier beginning with SCJ-. No explanation or punctuation outside the identifier."

@dataclass(frozen=True,slots=True)
class Case:
    object_key:str; page_index:int; expected_identifier:str; gold_source:str
@dataclass(frozen=True,slots=True)
class Result:
    case:Case; observed_text:str; observed_identifier:str|None; passed:bool; model:str; input_tokens:int|None; output_tokens:int|None; thinking_tokens:int|None; cost_usd:float|None; latency_ms:int; routed_provider:str; error:str|None

def extract_identifier(text:str)->str|None:
    match=IDENTIFIER.search(text or "")
    return match.group(0).upper() if match else None

def _read_pdf(store:Any,key:str)->bytes:
    value=store.client.get_object(Bucket=store.config.bucket,Key=key)["Body"].read(); return value if isinstance(value,bytes) else bytes(value)

def discover_cases(store:Any,limit:int=500)->list[Case]:
    response=store.client.list_objects_v2(Bucket=store.config.bucket,Prefix=PREFIX,MaxKeys=min(1000,max(limit*4,100)))
    cases=[]
    for key in sorted(str(x.get("Key") or "") for x in response.get("Contents",[]) if str(x.get("Key") or "").endswith(".pdf")):
        source=_read_pdf(store,key)
        if not has_native_text(source): continue
        page=select_reference_page(source,min_reference_chars=800,max_pages_to_scan=120)
        if page is None: continue
        expected=extract_identifier(page.text)
        if expected: cases.append(Case(key,page.page_index,expected,"pdf_text_layer"))
        if len(cases)>=limit: break
    return cases

def page_text_boxes(pdf:bytes,index:int):
    import pypdfium2 as p
    d=p.PdfDocument(pdf)
    try:
        pg=d[index]
        try:
            w,h=pg.get_size(); tp=pg.get_textpage()
            try: text=tp.get_text_range(); boxes=[tuple(float(v) for v in tp.get_charbox(i)) for i in range(len(text))]
            finally: tp.close()
            return text,boxes,float(w),float(h)
        finally: pg.close()
    finally: d.close()

def render_crop(pdf:bytes,index:int,token:str)->bytes:
    import pypdfium2 as p
    text,boxes,w,h=page_text_boxes(pdf,index); start=text.casefold().find(token.casefold())
    if start<0: raise RuntimeError(f"gold identifier absent from text layer: {token}")
    bs=boxes[start:start+len(token)]; l=min(b[0] for b in bs); b=min(x[1] for x in bs); r=max(x[2] for x in bs); t=max(x[3] for x in bs)
    hm=max(80.,(r-l)*1.5); vm=max(36.,(t-b)*4.); crop=(max(0.,l-hm),max(0.,b-vm),max(0.,w-r-hm),max(0.,h-t-vm))
    d=p.PdfDocument(pdf)
    try:
        pg=d[index]
        try: im=pg.render(scale=3.,crop=crop).to_pil(); out=io.BytesIO(); im.save(out,format="PNG"); return out.getvalue()
        finally: pg.close()
    finally: d.close()

def main()->int:
    if not 0<MAX_COST_USD<=1: raise ValueError("invalid aggregate cost cap")
    settings=get_openrouter_settings()
    if settings.api_key is None: raise RuntimeError("OPENROUTER_API_KEY is required")
    store=build_s3_object_store(); pool=load_manifest(MANIFEST) if MANIFEST else discover_cases(store,max(500,SAMPLE_SIZE)); cases=select_cases(pool)
    provider=OpenRouterVisualModelProvider(api_key=settings.api_key.get_secret_value(),model=MODEL,base_url=settings.base_url,reasoning_effort=REASONING,structured_mode="raw_text",provider_order=PROVIDER_ORDER,allow_provider_fallbacks=not bool(PROVIDER_ORDER))
    results=[]; total=0.0; OUTPUT.mkdir(parents=True,exist_ok=True)
    for i,case in enumerate(cases):
        image=render_crop(_read_pdf(store,case.object_key),case.page_index,case.expected_identifier); (OUTPUT/f"case-{i:04d}.png").write_bytes(image); started=time.perf_counter()
        try:
            response=provider.verify_image_text(image=image,media_type="image/png",prompt=PROMPT,json_schema={"type":"object"},max_output_tokens=64)
            raw=str(response.value.get("transcription") or "").strip(); observed=extract_identifier(raw); cost=response.cost_usd or 0.; total+=cost
            result=Result(case,raw,observed,observed==case.expected_identifier,response.model,response.usage.input_tokens,response.usage.output_tokens,response.usage.thinking_tokens,response.cost_usd,int((time.perf_counter()-started)*1000),str(response.provider_metadata.get("routed_provider") or ""),None)
        except ModelProviderError as exc:
            result=Result(case,"",None,False,MODEL,None,None,None,None,int((time.perf_counter()-started)*1000),"",str(exc))
        results.append(result)
        if total>MAX_COST_USD: raise RuntimeError(f"aggregate visual benchmark cost ${total:.6f} exceeded ${MAX_COST_USD:.6f}")
    passed=sum(r.passed for r in results); payload={"schema_version":6,"benchmark_kind":"visual_identifier_transcription","selection":{"mode":SELECTION,"seed":SEED,"sample_size":SAMPLE_SIZE,"manifest":MANIFEST or None},"model":MODEL,"reasoning_effort":REASONING,"cases":len(results),"passed":passed,"failed":len(results)-passed,"accuracy":passed/len(results),"observed_cost_usd":total,"max_cost_usd":MAX_COST_USD,"results":[asdict(r) for r in results]}
    (OUTPUT/"results.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(payload,indent=2,ensure_ascii=False,sort_keys=True)); return 0 if passed==len(results) else 1
if __name__=="__main__": raise SystemExit(main())
