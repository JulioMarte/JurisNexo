"""Two-pass literal visual OCR for frozen SCJ Principales review pages.

Pass 1 reads the rendered page image without candidate text. Pass 2 receives the
same image plus pass 1 as an explicitly untrusted hypothesis. Evidence remains
page- and pass-addressable; a later pass never overwrites an earlier one.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider

MODEL = "inclusionai/ling-3.0-flash-vl"
PROVIDER = "novita"
PROVIDER_LABEL = "NovitaAI"
RENDER_SCALE = 2.0
PROMPT_CONTRACT = "scj-literal-ocr-v1"
MAX_OUTPUT_TOKENS = 8192
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"transcription": {"type": "string"}},
    "required": ["transcription"],
    "additionalProperties": False,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        if not 0 <= page_index < len(document):
            raise RuntimeError(f"page index outside source PDF: {page_index}")
        page = document[page_index]
        try:
            bitmap = page.render(scale=RENDER_SCALE)
            try:
                stream = io.BytesIO()
                bitmap.to_pil().save(stream, format="PNG")
                return stream.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _manifest_cases(pending: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(pending.get("cases"), list):
        return list(pending["cases"])
    rows: list[dict[str, Any]] = []
    for document in pending.get("documents", []):
        object_key = str(document["object_key"])
        source_sha = str(document["source_pdf_sha256"])
        for page in document["pages"]:
            rows.append(
                {
                    **page,
                    "object_key": object_key,
                    "source_pdf_sha256": source_sha,
                }
            )
    return rows


def _prompt(pass_number: int, previous_text: str | None) -> str:
    base = (
        "Transcribe literalmente TODO el texto visible de esta pagina judicial. "
        "La imagen es la unica autoridad. No resumas, no parafrasees, no corrijas "
        "ortografia, no modernices, no completes texto ausente y no inventes. "
        "Conserva palabras, numeros, acentos, signos, encabezados, pies, numeros de "
        "pagina y saltos de linea visibles con la mayor fidelidad posible. "
        "Devuelve unicamente la transcripcion en el campo transcription."
    )
    if pass_number == 1:
        if previous_text is not None:
            raise ValueError("pass 1 must not receive previous text")
        return base + " Esta es una lectura independiente de primera pasada."
    if pass_number != 2 or previous_text is None:
        raise ValueError("pass 2 requires previous text")
    return (
        base
        + "\n\nEsta es una segunda pasada adversarial. La transcripcion previa que sigue es "
        "solo una hipotesis NO confiable. No la copies por defecto. Comprueba cada "
        "linea contra la imagen y corrige cualquier omision, insercion, sustitucion, "
        "numero, acento, signo o fragmento alucinado. Si imagen e hipotesis chocan, "
        "manda la imagen.\n\nTRANSCRIPCION_PREVIA_NO_CONFIABLE:\n"
        + previous_text
    )


def _provider(api_key: str) -> OpenRouterVisualModelProvider:
    return OpenRouterVisualModelProvider(
        api_key=api_key,
        model=MODEL,
        timeout_seconds=180.0,
        reasoning_effort="none",
        structured_mode="tool",
        provider_order=(PROVIDER,),
        allow_provider_fallbacks=False,
    )


def _is_novita(value: object) -> bool:
    normalized = str(value or "").strip().casefold().replace(" ", "")
    return "novita" in normalized


def prepare(
    *, pending_manifest: Path, object_key: str, output: Path, shard_count: int
) -> dict[str, Any]:
    if shard_count != 20:
        raise ValueError("this benchmark contract requires exactly 20 shards")
    pending = json.loads(pending_manifest.read_text(encoding="utf-8"))
    cases = [
        row for row in _manifest_cases(pending)
        if str(row["object_key"]) == object_key
    ]
    if not cases:
        raise RuntimeError("selected PDF has no material pending OCR pages in manifest")
    cases.sort(key=lambda row: int(row["page_index"]))
    source_shas = {str(row["source_pdf_sha256"]) for row in cases}
    if len(source_shas) != 1:
        raise RuntimeError("pending manifest mixes source PDF identities")
    expected_sha = next(iter(source_shas))

    store = build_s3_object_store()
    response = store.client.get_object(Bucket=store.config.bucket, Key=object_key)
    body = response["Body"].read()
    pdf_bytes = body if isinstance(body, bytes) else bytes(body)
    actual_sha = _sha256(pdf_bytes)
    if actual_sha != expected_sha:
        raise RuntimeError("source PDF checksum drift from frozen pending manifest")

    for case in cases:
        image = _render_page(pdf_bytes, int(case["page_index"]))
        if _sha256(image) != str(case["image_sha256"]):
            raise RuntimeError(
                f"render checksum drift for page {case['page_index']}: paid OCR blocked"
            )

    output.mkdir(parents=True, exist_ok=True)
    (output / "source.pdf").write_bytes(pdf_bytes)
    source = {
        "schema_version": 1,
        "object_key": object_key,
        "source_pdf_sha256": actual_sha,
        "pending_manifest_sha256": _sha256(pending_manifest.read_bytes()),
        "pending_manifest_source": pending.get("source"),
        "case_count": len(cases),
        "cases": cases,
        "shard_count": shard_count,
        "render_scale": RENDER_SCALE,
        "model": MODEL,
        "provider_slug": PROVIDER,
        "provider_label": PROVIDER_LABEL,
        "allow_provider_fallbacks": False,
        "prompt_contract": PROMPT_CONTRACT,
    }
    (output / "source.json").write_bytes(_canonical_json(source))
    matrix = {
        "include": [
            {"shard_index": index, "shard_count": shard_count}
            for index in range(shard_count)
        ]
    }
    (output / "matrix.json").write_bytes(_canonical_json(matrix))
    return source


def _previous_by_sample(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    rows = _load_jsonl(path)
    result = {str(row["sample_id"]): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError("previous pass contains duplicate sample IDs")
    return result


def _call_with_retry(
    provider: OpenRouterVisualModelProvider, *, image: bytes, prompt: str
) -> tuple[Any, float]:
    last: Exception | None = None
    for attempt in range(1, 4):
        started = time.monotonic()
        try:
            result = provider.verify_image_text(
                image=image,
                media_type="image/png",
                prompt=prompt,
                json_schema=SCHEMA,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
            return result, (time.monotonic() - started) * 1000.0
        except ModelProviderError as exc:
            last = exc
            if attempt < 3:
                time.sleep(float(attempt * 2))
    assert last is not None
    raise last


def run_shard(
    *,
    source_pdf: Path,
    source_json: Path,
    pass_number: int,
    shard_index: int,
    shard_count: int,
    output: Path,
    previous_pages: Path | None = None,
) -> int:
    if pass_number not in {1, 2}:
        raise ValueError("pass_number must be 1 or 2")
    source = json.loads(source_json.read_text(encoding="utf-8"))
    if shard_count != 20 or int(source["shard_count"]) != 20:
        raise RuntimeError("source/shard contract requires exactly 20 shards")
    if not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index")
    if str(source["model"]) != MODEL or str(source["provider_slug"]) != PROVIDER:
        raise RuntimeError("source model/provider contract drift")
    if bool(source.get("allow_provider_fallbacks")):
        raise RuntimeError("provider fallback must remain disabled")

    pdf_bytes = source_pdf.read_bytes()
    if _sha256(pdf_bytes) != str(source["source_pdf_sha256"]):
        raise RuntimeError("source PDF checksum mismatch after fan-out")
    previous = _previous_by_sample(previous_pages)
    if pass_number == 1 and previous:
        raise RuntimeError("pass 1 cannot consume previous-pass evidence")
    if pass_number == 2 and not previous:
        raise RuntimeError("pass 2 requires aggregated pass-1 evidence")

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for live Ling OCR")
    provider = _provider(api_key)

    cases = list(source["cases"])
    owned = [
        case for position, case in enumerate(cases)
        if position % shard_count == shard_index
    ]
    records: list[dict[str, Any]] = []
    text_dir = output / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    for case in owned:
        sample_id = str(case["sample_id"])
        page_index = int(case["page_index"])
        image = _render_page(pdf_bytes, page_index)
        image_sha = _sha256(image)
        if image_sha != str(case["image_sha256"]):
            raise RuntimeError(f"render checksum drift for {sample_id}")

        previous_row = previous.get(sample_id)
        previous_text: str | None = None
        previous_sha: str | None = None
        if pass_number == 2:
            if previous_row is None:
                raise RuntimeError(f"pass 1 evidence missing for {sample_id}")
            previous_text = str(previous_row["transcription"])
            previous_sha = _sha256(previous_text.encode("utf-8"))
            if previous_sha != str(previous_row["transcription_sha256"]):
                raise RuntimeError(
                    f"pass 1 transcription checksum mismatch for {sample_id}"
                )

        prompt = _prompt(pass_number, previous_text)
        result, elapsed_ms = _call_with_retry(provider, image=image, prompt=prompt)
        routed = result.provider_metadata.get("routed_provider")
        if not _is_novita(routed):
            raise RuntimeError(
                f"strict provider pin violated for {sample_id}: "
                f"routed_provider={routed!r}"
            )
        transcription = str(result.value["transcription"])
        transcription_sha = _sha256(transcription.encode("utf-8"))
        record = {
            "schema_version": 1,
            "sample_id": sample_id,
            "object_key": source["object_key"],
            "source_pdf_sha256": source["source_pdf_sha256"],
            "page_index": page_index,
            "image_sha256": image_sha,
            "pass_number": pass_number,
            "prompt_contract": PROMPT_CONTRACT,
            "prompt_sha256": _sha256(prompt.encode("utf-8")),
            "previous_transcription_sha256": previous_sha,
            "transcription": transcription,
            "transcription_sha256": transcription_sha,
            "requested_model": MODEL,
            "returned_model": result.model,
            "requested_provider": PROVIDER,
            "requested_provider_label": PROVIDER_LABEL,
            "routed_provider": routed,
            "allow_provider_fallbacks": False,
            "response_id": result.response_id,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "thinking_tokens": result.usage.thinking_tokens,
            "total_tokens": result.usage.total_tokens,
            "cost_usd": result.cost_usd,
            "elapsed_ms": elapsed_ms,
            "shard_index": shard_index,
            "shard_count": shard_count,
        }
        records.append(record)
        (text_dir / f"page-{page_index:05d}.txt").write_text(
            transcription, encoding="utf-8"
        )

    output.mkdir(parents=True, exist_ok=True)
    (output / f"pages-{shard_index:02d}.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in records
        ),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "pass_number": pass_number,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "owned_pages": len(records),
        "cost_usd": sum(float(row.get("cost_usd") or 0.0) for row in records),
    }
    (output / f"summary-{shard_index:02d}.json").write_bytes(
        _canonical_json(summary)
    )
    return 0


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def aggregate(
    *,
    source_json: Path,
    input_root: Path,
    pass_number: int,
    output: Path,
    previous_pages: Path | None = None,
) -> int:
    source = json.loads(source_json.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for path in sorted(input_root.rglob("pages-*.jsonl")):
        records.extend(_load_jsonl(path))
    expected = {str(case["sample_id"]): case for case in source["cases"]}
    ids = [str(row["sample_id"]) for row in records]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    missing = sorted(set(expected) - set(ids))
    unexpected = sorted(set(ids) - set(expected))
    if duplicates or missing or unexpected:
        raise RuntimeError(
            "pass reconciliation failed: "
            f"duplicates={duplicates} missing={missing} unexpected={unexpected}"
        )
    for row in records:
        case = expected[str(row["sample_id"])]
        if int(row["pass_number"]) != pass_number:
            raise RuntimeError("mixed pass numbers in aggregate")
        if str(row["source_pdf_sha256"]) != str(case["source_pdf_sha256"]):
            raise RuntimeError("source provenance mismatch in pass aggregate")
        if str(row["image_sha256"]) != str(case["image_sha256"]):
            raise RuntimeError("image provenance mismatch in pass aggregate")
        if not _is_novita(row.get("routed_provider")):
            raise RuntimeError("non-Novita observation found in strict aggregate")

    previous = _previous_by_sample(previous_pages)
    review: list[dict[str, Any]] = []
    exact = 0
    similarities: list[float] = []
    if pass_number == 2:
        if set(previous) != set(expected):
            raise RuntimeError("pass-1 aggregate does not match frozen case set")
        for row in records:
            before = previous[str(row["sample_id"])]
            before_text = str(before["transcription"])
            before_sha = str(before["transcription_sha256"])
            if str(row.get("previous_transcription_sha256")) != before_sha:
                raise RuntimeError(
                    "pass-2 input linkage does not match pass-1 evidence"
                )
            after_text = str(row["transcription"])
            same = before_sha == str(row["transcription_sha256"])
            score = _similarity(before_text, after_text)
            row["pass1_pass2_exact_match"] = same
            row["pass1_pass2_similarity"] = score
            exact += int(same)
            similarities.append(score)
            if not same:
                review.append(
                    {
                        "sample_id": row["sample_id"],
                        "object_key": row["object_key"],
                        "page_index": row["page_index"],
                        "image_sha256": row["image_sha256"],
                        "pass1_transcription_sha256": before_sha,
                        "pass2_transcription_sha256": row["transcription_sha256"],
                        "similarity": score,
                        "review_reason": "pass_disagreement",
                    }
                )

    records.sort(key=lambda row: int(row["page_index"]))
    output.mkdir(parents=True, exist_ok=True)
    (output / "pages.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in records
        ),
        encoding="utf-8",
    )
    final_dir = output / "final-candidate-text"
    final_dir.mkdir(exist_ok=True)
    for row in records:
        (final_dir / f"page-{int(row['page_index']):05d}.txt").write_text(
            str(row["transcription"]), encoding="utf-8"
        )
    (output / "review.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in review),
        encoding="utf-8",
    )
    total_cost = sum(float(row.get("cost_usd") or 0.0) for row in records)
    summary = {
        "schema_version": 1,
        "object_key": source["object_key"],
        "source_pdf_sha256": source["source_pdf_sha256"],
        "pass_number": pass_number,
        "pages": len(records),
        "model": MODEL,
        "provider": PROVIDER_LABEL,
        "provider_slug": PROVIDER,
        "provider_fallbacks": False,
        "prompt_contract": PROMPT_CONTRACT,
        "total_cost_usd": total_cost,
        "exact_match_with_previous": exact if pass_number == 2 else None,
        "changed_from_previous": len(review) if pass_number == 2 else None,
        "minimum_pass_similarity": min(similarities) if similarities else None,
        "mean_pass_similarity": (
            sum(similarities) / len(similarities) if similarities else None
        ),
        "semantic_status": (
            "second_pass_candidate_not_primary_source_gold"
            if pass_number == 2
            else "first_pass_observation"
        ),
    }
    (output / "summary.json").write_bytes(_canonical_json(summary))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--pending-manifest", type=Path, required=True)
    p.add_argument("--object-key", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--shard-count", type=int, default=20)

    s = sub.add_parser("shard")
    s.add_argument("--source-pdf", type=Path, required=True)
    s.add_argument("--source-json", type=Path, required=True)
    s.add_argument("--pass-number", type=int, choices=[1, 2], required=True)
    s.add_argument("--shard-index", type=int, required=True)
    s.add_argument("--shard-count", type=int, default=20)
    s.add_argument("--previous-pages", type=Path)
    s.add_argument("--output", type=Path, required=True)

    a = sub.add_parser("aggregate")
    a.add_argument("--source-json", type=Path, required=True)
    a.add_argument("--input-root", type=Path, required=True)
    a.add_argument("--pass-number", type=int, choices=[1, 2], required=True)
    a.add_argument("--previous-pages", type=Path)
    a.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(
            pending_manifest=args.pending_manifest,
            object_key=args.object_key,
            output=args.output,
            shard_count=args.shard_count,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "shard":
        return run_shard(
            source_pdf=args.source_pdf,
            source_json=args.source_json,
            pass_number=args.pass_number,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            output=args.output,
            previous_pages=args.previous_pages,
        )
    return aggregate(
        source_json=args.source_json,
        input_root=args.input_root,
        pass_number=args.pass_number,
        output=args.output,
        previous_pages=args.previous_pages,
    )


if __name__ == "__main__":
    raise SystemExit(main())
