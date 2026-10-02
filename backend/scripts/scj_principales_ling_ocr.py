"""Two-pass Ling OCR for unresolved SCJ Principales pages."""
from __future__ import annotations
import argparse, hashlib, io, json, os, tarfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any
import pypdfium2 as pdfium
from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
CENSUS_PREFIX="benchmarks/scj-principales/corpus-verification/v1/"
OUTPUT_PREFIX="benchmarks/scj-principales/ling-ocr/v1"
MODEL="inclusionai/ling-3.0-flash-vl"; PROVIDER="novita"; WORKERS=20; RENDER_SCALE=2.0
PENDING=frozenset({"misaligned","no_native_text"})
PASS1=("Transcribe every visible character on this Dominican court page literally. Preserve spelling, accents, punctuation, numbers, names and meaningful line breaks. Do not summarize, normalize, correct, infer missing words, or add commentary. Return only the transcription.")
PASS2=("Adversarially verify the OCR draft below against the page image. The image is the authority. Silently correct every omission, insertion, substitution, accent, punctuation, number, name, spacing or meaningful line-break error. Never modernize or improve the source. Return only the most literal transcription visible in the image.\n\nFIRST-PASS OCR DRAFT:\n")
def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def _json(value:object)->bytes:return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _list(store:Any,prefix:str)->list[dict[str,Any]]:
 rows=[];token=None
 while True:
  kwargs={"Bucket":store.config.bucket,"Prefix":prefix,"MaxKeys":1000}
  if token:kwargs["ContinuationToken"]=token
  response=store.client.list_objects_v2(**kwargs);rows.extend(x for x in response.get("Contents",[]) if isinstance(x,dict))
  if not response.get("IsTruncated"):return rows
  token=str(response.get("NextContinuationToken") or "")
  if not token:raise RuntimeError("truncated S3 listing lacks continuation token")
def _get(store:Any,key:str)->bytes:
 body=store.client.get_object(Bucket=store.config.bucket,Key=key)["Body"].read();return body if isinstance(body,bytes) else bytes(body)
def _maybe_json(store:Any,key:str)->dict[str,Any]|None:
 try:return json.loads(_get(store,key))
 except Exception as exc:
  if store.is_not_found(exc):return None
  raise
def _put_immutable(store:Any,key:str,value:object)->None:
 payload=_json(value);digest=_sha(payload)
 try:head=store.client.head_object(Bucket=store.config.bucket,Key=key)
 except Exception as exc:
  if not store.is_not_found(exc):raise
 else:
  metadata=head.get("Metadata",{}) if isinstance(head,dict) else {}
  if str(metadata.get("payload-sha256") or "")!=digest:raise RuntimeError(f"immutable OCR evidence collision: {key}")
  return
 store.put(key=key,content=payload,content_type="application/json",metadata={"payload-sha256":digest})
def _latest_census(store:Any)->tuple[str,dict[str,Any]]:
 successes=[x for x in _list(store,CENSUS_PREFIX) if str(x.get("Key") or "").endswith("/_SUCCESS.json")]
 if not successes:raise RuntimeError("no completed SCJ Principales census generation found")
 chosen=max(successes,key=lambda x:x.get("LastModified") or "");key=str(chosen["Key"]);return key.rsplit("/_SUCCESS.json",1)[0],json.loads(_get(store,key))
def _documents(store:Any,prefix:str)->list[dict[str,Any]]:
 keys=sorted(str(x["Key"]) for x in _list(store,f"{prefix}/documents/") if str(x.get("Key") or "").endswith(".tar.gz"));result=[]
 for key in keys:
  with tarfile.open(fileobj=io.BytesIO(_get(store,key)),mode="r:gz") as archive:
   dm=archive.extractfile("document.json");pm=archive.extractfile("pages.jsonl")
   if dm is None or pm is None:raise RuntimeError(f"incomplete census archive: {key}")
   doc=json.loads(dm.read());pages=[json.loads(line) for line in pm.read().decode().splitlines() if line.strip()]
  pending=sorted(int(p["page_index"]) for p in pages if p.get("classification") in PENDING)
  if pending:result.append({"document_id":doc["document_id"],"object_key":doc["object_key"],"source_pdf_sha256":doc["source_pdf_sha256"],"page_count":doc["page_count"],"pending_pages":pending,"classification_by_page":{int(p["page_index"]):p.get("classification") for p in pages}})
 return result
def inventory(output:Path)->dict[str,Any]:
 store=build_s3_object_store();prefix,success=_latest_census(store);docs=_documents(store,prefix)
 payload={"schema_version":1,"census_prefix":prefix,"census_success":success,"pending_classifications":sorted(PENDING),"document_count":len(docs),"pending_page_count":sum(len(d["pending_pages"]) for d in docs),"model":MODEL,"provider":PROVIDER,"workers":WORKERS,"passes":2,"documents":docs}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(_json(payload));return payload
def _render(document:Any,page_index:int)->bytes:
 page=document[page_index]
 try:
  bitmap=page.render(scale=RENDER_SCALE)
  try:image=bitmap.to_pil();stream=io.BytesIO();image.save(stream,format="PNG");return stream.getvalue()
  finally:bitmap.close()
 finally:page.close()
def _provider(key:str)->OpenRouterVisualModelProvider:return OpenRouterVisualModelProvider(api_key=key,model=MODEL,reasoning_effort="none",structured_mode="raw_text",provider_order=(PROVIDER,),allow_provider_fallbacks=False,timeout_seconds=300.0)
def _call(provider:OpenRouterVisualModelProvider,image:bytes,prompt:str)->dict[str,Any]:
 last=None
 for attempt in range(1,4):
  started=time.perf_counter()
  try:
   r=provider.verify_image_text(image=image,media_type="image/png",prompt=prompt,json_schema={},max_output_tokens=None);routed=str(r.provider_metadata.get("routed_provider") or "")
   if PROVIDER not in routed.lower():raise RuntimeError(f"provider pin violated: {routed!r}")
   return {"transcription":str(r.value["transcription"]),"model_returned":r.model,"routed_provider":routed,"response_id":r.response_id,"usage":asdict(r.usage),"cost_usd":r.cost_usd,"latency_ms":int((time.perf_counter()-started)*1000),"attempt":attempt}
  except Exception as exc:
   last=exc
   if attempt<3:time.sleep(2**(attempt-1))
 assert last is not None;raise last
def _key(generation:str,sha:str,page:int,pass_no:int)->str:return f"{OUTPUT_PREFIX}/{generation}/{sha}/pages/{page+1:06d}/pass-{pass_no}.json"
def _record(doc:dict[str,Any],page:int,image:bytes,pass_no:int,call:dict[str,Any],first:dict[str,Any]|None)->dict[str,Any]:
 record={"schema_version":1,"evidence_id":f"{doc['source_pdf_sha256']}:page-{page+1}:pass-{pass_no}","document_id":doc["document_id"],"object_key":doc["object_key"],"source_pdf_sha256":doc["source_pdf_sha256"],"page_index":page,"page_number":page+1,"prior_classification":doc["classification_by_page"].get(str(page),doc["classification_by_page"].get(page)),"render_sha256":_sha(image),"render_scale":RENDER_SCALE,"pass":pass_no,"prompt_version":f"ling-literal-ocr-v1-pass-{pass_no}","model_requested":MODEL,"provider_requested":PROVIDER,"provider_fallbacks_allowed":False,**call}
 if first is not None:
  draft=str(first["transcription"]);record["first_pass_evidence_id"]=first["evidence_id"];record["first_pass_transcription_sha256"]=_sha(draft.encode());record["first_pass_transcription"]=draft
 return record
def _page(provider:OpenRouterVisualModelProvider,store:Any,generation:str,doc:dict[str,Any],page:int,image:bytes)->tuple[float,bool]:
 k1=_key(generation,doc["source_pdf_sha256"],page,1);k2=_key(generation,doc["source_pdf_sha256"],page,2)
 if _maybe_json(store,k2) is not None:return 0.0,False
 first=_maybe_json(store,k1);cost=0.0
 if first is None:
  c1=_call(provider,image,PASS1);first=_record(doc,page,image,1,c1,None);_put_immutable(store,k1,first);cost+=float(c1.get("cost_usd") or 0.0)
 c2=_call(provider,image,PASS2+str(first["transcription"]));second=_record(doc,page,image,2,c2,first);_put_immutable(store,k2,second);cost+=float(c2.get("cost_usd") or 0.0);return cost,True
def run(inventory_path:Path,output:Path,max_cost_usd:float,max_new_pages:int|None)->dict[str,Any]:
 if max_cost_usd<=0:raise ValueError("max_cost_usd must be positive")
 api_key=os.environ.get("OPENROUTER_API_KEY","").strip()
 if not api_key:raise RuntimeError("OPENROUTER_API_KEY is required")
 inv=json.loads(inventory_path.read_text());generation=_sha(str(inv["census_prefix"]).encode())[:16];store=build_s3_object_store();provider=_provider(api_key);total=0.0;new=0;skipped=0;visited=0;failures=[];stop=False
 for doc in inv["documents"]:
  if stop:break
  pdf=_get(store,doc["object_key"])
  if _sha(pdf)!=doc["source_pdf_sha256"]:raise RuntimeError(f"source SHA drift: {doc['object_key']}")
  document=pdfium.PdfDocument(pdf)
  try:
   pages=list(doc["pending_pages"])
   for offset in range(0,len(pages),WORKERS):
    work=[]
    for page in pages[offset:offset+WORKERS]:
     if _maybe_json(store,_key(generation,doc["source_pdf_sha256"],page,2)) is not None:skipped+=1;continue
     if max_new_pages is not None and new+len(work)>=max_new_pages:stop=True;break
     work.append((page,_render(document,page)))
    if not work:
     if stop:break
     continue
    with ThreadPoolExecutor(max_workers=min(WORKERS,len(work))) as pool:
     futures={pool.submit(_page,provider,store,generation,doc,page,image):page for page,image in work}
     for future in as_completed(futures):
      page=futures[future]
      try:cost,created=future.result();total+=cost;new+=int(created)
      except Exception as exc:failures.append({"document_id":doc["document_id"],"object_key":doc["object_key"],"page_index":page,"error":str(exc)})
    if total>max_cost_usd:stop=True;break
   visited+=1
  finally:document.close()
 summary={"schema_version":1,"census_prefix":inv["census_prefix"],"generation_id":generation,"model":MODEL,"provider":PROVIDER,"provider_fallbacks_allowed":False,"workers":WORKERS,"passes":2,"pending_page_count":inv["pending_page_count"],"new_pages_completed":new,"already_complete_pages_skipped":skipped,"documents_visited":visited,"new_inference_cost_usd":round(total,10),"max_cost_usd":max_cost_usd,"cost_cap_reached":total>max_cost_usd,"failure_count":len(failures),"failures":failures,"complete":not stop and not failures,"note":"Cost is summed from OpenRouter usage.cost for newly executed calls; resumed evidence is neither charged nor counted again."}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(_json(summary));run_key=f"{OUTPUT_PREFIX}/{generation}/runs/{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}.json";_put_immutable(store,run_key,summary);return summary
def main()->int:
 parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True);inv=sub.add_parser("inventory");inv.add_argument("--output",type=Path,required=True);exe=sub.add_parser("run");exe.add_argument("--inventory",type=Path,required=True);exe.add_argument("--output",type=Path,required=True);exe.add_argument("--max-cost-usd",type=float,required=True);exe.add_argument("--max-new-pages",type=int);args=parser.parse_args();result=inventory(args.output) if args.command=="inventory" else run(args.inventory,args.output,args.max_cost_usd,args.max_new_pages);print(json.dumps({k:v for k,v in result.items() if k!="documents"},indent=2,ensure_ascii=False,sort_keys=True));return 0 if not result.get("failure_count") else 1
if __name__=="__main__":raise SystemExit(main())
