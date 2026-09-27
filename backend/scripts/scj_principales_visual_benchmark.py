from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.gold import (
    assess_reference_text_health,
    score_text_fidelity,
)
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)
from jurisnexo.normalization.visual_reference_ocr import (
    run_tesseract_visual_ocr,
)
from jurisnexo.normalization.visual_page_benchmark import (
    VisualPageCase,
    load_visual_page_manifest,
    select_visual_page_cases,
)

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"),
)
from scj_page_selection import has_native_text, select_reference_pages  # noqa: E402

OUTPUT = Path(
    os.environ.get(
        "SCJ_VISUAL_OUTPUT",
        "scj-principales-visual-benchmark-output",
    )
)
STAGE = os.environ.get("SCJ_VISUAL_STAGE", "prepare")
PREPARED_MANIFEST = Path(
    os.environ.get("SCJ_VISUAL_PREPARED_MANIFEST", "prepared-manifest.json")
)
MODEL = os.environ.get(
    "JURISNEXO_OPENROUTER_VISUAL_MODEL",
    "google/gemini-2.5-flash-lite",
)
REASONING = os.environ.get("SCJ_VISUAL_REASONING", "none")
PROVIDER_ORDER = tuple(
    part.strip()
    for part in os.environ.get("SCJ_VISUAL_PROVIDER_ORDER", "").split(",")
    if part.strip()
)
SAMPLE_SIZE = int(os.environ.get("SCJ_VISUAL_SAMPLE_SIZE", "1"))
SEED = int(os.environ.get("SCJ_VISUAL_SEED", "20260926"))
SELECTION = os.environ.get("SCJ_VISUAL_SELECTION", "deterministic")
CURATED_MANIFEST = os.environ.get("SCJ_VISUAL_CURATED_MANIFEST", "").strip()
MAX_CONCURRENCY = int(os.environ.get("SCJ_VISUAL_MAX_CONCURRENCY", "20"))
ALIGNMENT_AUDIT_SIZE = int(
    os.environ.get(
        "SCJ_VISUAL_ALIGNMENT_AUDIT_SIZE",
        str(max(SAMPLE_SIZE * 10, 20)),
    )
)
MIN_ALIGNMENT_AUDIT_SIZE = int(
    os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_AUDIT_SIZE", "20")
)
TESSERACT_LANGUAGE = os.environ.get(
    "SCJ_VISUAL_TESSERACT_LANGUAGE",
    "spa+eng",
)
ALIGNMENT_POLICY = VisualReferencePolicy(
    minimum_native_characters=int(
        os.environ.get("SCJ_VISUAL_MIN_NATIVE_CHARS", "800")
    ),
    minimum_ocr_characters=int(
        os.environ.get("SCJ_VISUAL_MIN_OCR_CHARS", "600")
    ),
    minimum_ocr_mean_confidence=float(
        os.environ.get("SCJ_VISUAL_MIN_OCR_CONFIDENCE", "90")
    ),
    maximum_word_error_rate=float(
        os.environ.get("SCJ_VISUAL_MAX_ALIGNMENT_WER", "0.10")
    ),
    maximum_character_error_rate=float(
        os.environ.get("SCJ_VISUAL_MAX_ALIGNMENT_CER", "0.08")
    ),
    minimum_token_content_recall=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_RECALL", "0.98")
    ),
    minimum_token_content_precision=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_PRECISION", "0.98")
    ),
    minimum_token_order_preservation=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_ORDER", "0.98")
    ),
    minimum_legal_critical_recall=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_CRITICAL", "1.0")
    ),
)
PREFIX = "jurisdictions/do/scj/principales-sentencias/"
PROMPT = (
    "Transcribe every visible word exactly as written. "
    "Return only the transcription. "
    "Do not explain, correct spelling, summarize, or infer missing text."
)


@dataclass(frozen=True, slots=True)
class ModelPageResult:
    sample_id: str
    object_key: str
    page_index: int
    gold_source: str
    model: str
    routed_provider: str
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    retry_count: int
    character_error_rate: float | None
    word_error_rate: float | None
    token_content_recall: float | None
    token_content_precision: float | None
    token_content_f1: float | None
    token_order_preservation: float | None
    legal_critical_recall: float | None
    reference_reliable: bool
    error: str | None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_pdf(store: Any, key: str) -> bytes:
    body = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _native_text(pdf_bytes: bytes, page_index: int) -> str:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            text_page = page.get_textpage()
            try:
                return text_page.get_text_range()
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def _render_page(pdf_bytes: bytes, page_index: int) -> bytes:
    import io

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=2.0)
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
            raise RuntimeError(
                "S3 listing truncated without continuation token"
            )
    return sorted(set(keys))


def _discover_cases(
    store: Any,
    *,
    limit: int,
) -> list[VisualPageCase]:
    if limit < 1:
        raise ValueError("limit must be positive")

    # Build several distributed body-page candidates per document, then
    # interleave by page rank. This preserves document diversity: every
    # eligible PDF contributes its first candidate before any PDF contributes
    # a second one. The admission gate remains unchanged; this only gives it a
    # sufficiently large local pool to find aligned pages without weakening
    # quality thresholds.
    per_document: list[list[VisualPageCase]] = []
    max_pages_per_document = 4
    for key in _list_pdf_keys(store):
        try:
            pdf_bytes = _read_pdf(store, key)
        except Exception:
            continue
        if not has_native_text(pdf_bytes):
            continue
        selected_pages = select_reference_pages(
            pdf_bytes,
            min_reference_chars=800,
            max_pages_to_scan=120,
            max_pages_per_document=max_pages_per_document,
        )
        if not selected_pages:
            continue
        per_document.append(
            [
                VisualPageCase(
                    object_key=key,
                    page_index=selected.page_index,
                    gold_source="pdf_text_layer",
                )
                for selected in selected_pages
            ]
        )

    cases: list[VisualPageCase] = []
    for page_rank in range(max_pages_per_document):
        for document_cases in per_document:
            if page_rank >= len(document_cases):
                continue
            cases.append(document_cases[page_rank])
            if len(cases) >= limit:
                return cases
    return cases


def _prepare() -> int:
    if SAMPLE_SIZE < 1 or SAMPLE_SIZE > 500:
        raise ValueError("SCJ_VISUAL_SAMPLE_SIZE must be between 1 and 500")
    if ALIGNMENT_AUDIT_SIZE < SAMPLE_SIZE:
        raise ValueError(
            "SCJ_VISUAL_ALIGNMENT_AUDIT_SIZE must be >= sample size"
        )

    store = build_s3_object_store()
    pool = (
        load_visual_page_manifest(CURATED_MANIFEST)
        if CURATED_MANIFEST
        else _discover_cases(
            store,
            limit=max(100, SAMPLE_SIZE * 10, ALIGNMENT_AUDIT_SIZE),
        )
    )
    if len(pool) < SAMPLE_SIZE:
        raise RuntimeError(
            f"only {len(pool)} candidate pages available for "
            f"{SAMPLE_SIZE} requested pages"
        )

    audit_candidates = pool[: min(len(pool), ALIGNMENT_AUDIT_SIZE)]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    evidence_root = OUTPUT / "alignment-evidence"
    audit_records: list[dict[str, Any]] = []
    aligned_cases: list[VisualPageCase] = []
    aligned_payloads: dict[tuple[str, int], dict[str, Any]] = {}
    rejection_reasons: Counter[str] = Counter()

    for audit_index, case in enumerate(audit_candidates):
        audit_id = f"audit-{audit_index:04d}"
        pdf_bytes = _read_pdf(store, case.object_key)
        reference = _native_text(pdf_bytes, case.page_index)
        image = _render_page(pdf_bytes, case.page_index)
        visual = run_tesseract_visual_ocr(
            image,
            language=TESSERACT_LANGUAGE,
        )
        assessment = assess_visual_reference_alignment(
            native_text=reference,
            ocr_text=visual.text,
            ocr_mean_confidence=visual.mean_confidence,
            policy=ALIGNMENT_POLICY,
        )
        assessment_json = assessment.to_json_dict()
        record = {
            "audit_id": audit_id,
            "object_key": case.object_key,
            "page_index": case.page_index,
            "gold_source": case.gold_source,
            "accepted": assessment.accepted,
            "assessment": assessment_json,
            "source_pdf_sha256": _sha256(pdf_bytes),
            "native_text_sha256": _sha256(reference.encode("utf-8")),
            "visual_ocr_sha256": _sha256(visual.text.encode("utf-8")),
            "image_sha256": _sha256(image),
            "visual_ocr_engine": visual.engine_version,
            "visual_ocr_language": visual.language,
        }
        audit_records.append(record)
        score = assessment.score
        print(
            json.dumps(
                {
                    "alignment_audit": audit_id,
                    "accepted": assessment.accepted,
                    "reasons": list(assessment.rejection_reasons),
                    "wer": score.word_error_rate,
                    "cer": score.character_error_rate,
                    "recall": score.token_content_recall,
                    "precision": score.token_content_precision,
                    "order": score.token_order_preservation,
                    "critical": score.legal_critical_recall,
                    "ocr_confidence": visual.mean_confidence,
                    "native_chars": len(reference),
                    "ocr_chars": len(visual.text),
                },
                sort_keys=True,
            ),
            flush=True,
        )

        audit_dir = (
            evidence_root
            / ("accepted" if assessment.accepted else "rejected")
            / audit_id
        )
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "input-page.png").write_bytes(image)
        (audit_dir / "reference-native.txt").write_text(
            reference,
            encoding="utf-8",
        )
        (audit_dir / "reference-visual-ocr.txt").write_text(
            visual.text,
            encoding="utf-8",
        )
        (audit_dir / "alignment.json").write_text(
            json.dumps(
                record,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        if assessment.accepted:
            aligned_case = VisualPageCase(
                object_key=case.object_key,
                page_index=case.page_index,
                gold_source="aligned_native_visual",
            )
            aligned_cases.append(aligned_case)
            aligned_payloads[
                (case.object_key, case.page_index)
            ] = {
                "reference": reference,
                "image": image,
                "visual_text": visual.text,
                "source_pdf_sha256": _sha256(pdf_bytes),
                "alignment": assessment_json,
                "visual_ocr_engine": visual.engine_version,
                "visual_ocr_language": visual.language,
            }
        else:
            rejection_reasons.update(assessment.rejection_reasons)

        audited_count = audit_index + 1
        if (
            len(aligned_cases) >= SAMPLE_SIZE
            and audited_count >= MIN_ALIGNMENT_AUDIT_SIZE
        ):
            break

    (OUTPUT / "alignment-audit.jsonl").write_text(
        "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for record in audit_records
        ),
        encoding="utf-8",
    )
    audit_summary = {
        "audited_candidates": len(audit_records),
        "accepted_candidates": len(aligned_cases),
        "rejected_candidates": len(audit_records) - len(aligned_cases),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "policy": asdict(ALIGNMENT_POLICY),
    }
    (OUTPUT / "alignment-summary.json").write_text(
        json.dumps(
            audit_summary,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if len(aligned_cases) < SAMPLE_SIZE:
        print(json.dumps(audit_summary, sort_keys=True), flush=True)
        raise RuntimeError(
            f"needed {SAMPLE_SIZE} aligned pages, found "
            f"{len(aligned_cases)} after auditing "
            f"{len(audit_records)} candidates"
        )

    selected = select_visual_page_cases(
        aligned_cases,
        sample_size=SAMPLE_SIZE,
        selection=SELECTION,
        seed=SEED,
    )
    manifest_cases: list[dict[str, Any]] = []
    for index, case in enumerate(selected):
        sample_id = f"case-{index:04d}"
        case_dir = OUTPUT / "cases" / sample_id
        case_dir.mkdir(parents=True, exist_ok=True)
        evidence = aligned_payloads[(case.object_key, case.page_index)]
        reference = str(evidence["reference"])
        image = bytes(evidence["image"])
        visual_text = str(evidence["visual_text"])

        reference_path = case_dir / "reference-native.txt"
        visual_reference_path = case_dir / "reference-visual-ocr.txt"
        image_path = case_dir / "input-page.png"
        metadata_path = case_dir / "source.json"
        reference_path.write_text(reference, encoding="utf-8")
        visual_reference_path.write_text(
            visual_text,
            encoding="utf-8",
        )
        image_path.write_bytes(image)

        metadata = {
            "sample_id": sample_id,
            "object_key": case.object_key,
            "page_index": case.page_index,
            "gold_source": "aligned_native_visual",
            "source_pdf_sha256": evidence["source_pdf_sha256"],
            "reference_sha256": _sha256(reference.encode("utf-8")),
            "visual_reference_sha256": _sha256(
                visual_text.encode("utf-8")
            ),
            "image_sha256": _sha256(image),
            "reference_characters": len(reference),
            "reference_reliable": True,
            "reference_authority": "dual_channel_aligned",
            "reference_caveat": (
                "Native PDF text is used for scoring only because an "
                "independent OCR reading of the exact rendered page passed "
                "the admission policy. The preserved image remains the "
                "primary human-auditable evidence."
            ),
            "alignment": evidence["alignment"],
            "visual_ocr_engine": evidence["visual_ocr_engine"],
            "visual_ocr_language": evidence["visual_ocr_language"],
        }
        metadata_path.write_text(
            json.dumps(
                metadata,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_cases.append(
            {
                **metadata,
                "reference_path": str(
                    reference_path.relative_to(OUTPUT)
                ),
                "visual_reference_path": str(
                    visual_reference_path.relative_to(OUTPUT)
                ),
                "image_path": str(image_path.relative_to(OUTPUT)),
                "metadata_path": str(
                    metadata_path.relative_to(OUTPUT)
                ),
            }
        )

    audited = len(audit_records)
    accepted = sum(
        bool(record["accepted"]) for record in audit_records
    )
    manifest = {
        "schema_version": 2,
        "benchmark_kind": "full_page_visual_transcription",
        "selection": {
            "mode": SELECTION,
            "seed": SEED,
            "sample_size": SAMPLE_SIZE,
            "curated_manifest": CURATED_MANIFEST or None,
        },
        "reference_admission": {
            "kind": "dual_channel_visual_native",
            "audited_candidates": audited,
            "accepted_candidates": accepted,
            "rejected_candidates": audited - accepted,
            "observed_acceptance_rate": (
                accepted / audited if audited else 0.0
            ),
            "rejection_reasons": dict(
                sorted(rejection_reasons.items())
            ),
            "visual_ocr_language": TESSERACT_LANGUAGE,
            "policy": asdict(ALIGNMENT_POLICY),
        },
        "prompt": PROMPT,
        "cases": manifest_cases,
    }
    (OUTPUT / "prepared-manifest.json").write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "prepared_cases": len(manifest_cases),
                "audited_candidates": audited,
                "accepted_candidates": accepted,
                "observed_acceptance_rate": (
                    accepted / audited if audited else 0.0
                ),
                "output": str(OUTPUT),
            },
            sort_keys=True,
        )
    )
    return 0


def _provider() -> OpenRouterVisualModelProvider:
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return OpenRouterVisualModelProvider(
        api_key=settings.api_key.get_secret_value(),
        model=MODEL,
        base_url=settings.base_url,
        timeout_seconds=120.0,
        reasoning_effort=REASONING,
        structured_mode="raw_text",
        provider_order=PROVIDER_ORDER,
        allow_provider_fallbacks=not bool(PROVIDER_ORDER),
    )


def _is_transient_provider_error(exc: ModelProviderError) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in (
            "HTTP 429",
            "HTTP 500",
            "HTTP 502",
            "HTTP 503",
            "HTTP 504",
        )
    )


def _run_one(
    *,
    provider: OpenRouterVisualModelProvider,
    prepared_root: Path,
    case: dict[str, Any],
    result_root: Path,
) -> ModelPageResult:
    sample_id = str(case["sample_id"])
    reference = (
        prepared_root / str(case["reference_path"])
    ).read_text(encoding="utf-8")
    image = (
        prepared_root / str(case["image_path"])
    ).read_bytes()
    started = time.perf_counter()
    retry_count = 0

    try:
        while True:
            try:
                response = provider.verify_image_text(
                    image=image,
                    media_type="image/png",
                    prompt=PROMPT,
                    json_schema={"type": "object"},
                    max_output_tokens=None,
                )
                break
            except ModelProviderError as exc:
                if (
                    retry_count >= 2
                    or not _is_transient_provider_error(exc)
                ):
                    raise
                time.sleep(0.5 * (2**retry_count))
                retry_count += 1

        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_text = str(
            response.value.get("transcription") or ""
        )
        score = score_text_fidelity(
            expected_text=reference,
            candidate_text=raw_text,
        )
        result = ModelPageResult(
            sample_id=sample_id,
            object_key=str(case["object_key"]),
            page_index=int(case["page_index"]),
            gold_source=str(case["gold_source"]),
            model=response.model,
            routed_provider=str(
                response.provider_metadata.get("routed_provider") or ""
            ),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=response.usage.thinking_tokens,
            total_tokens=response.usage.total_tokens,
            cost_usd=response.cost_usd,
            latency_ms=latency_ms,
            retry_count=retry_count,
            character_error_rate=score.character_error_rate,
            word_error_rate=score.word_error_rate,
            token_content_recall=score.token_content_recall,
            token_content_precision=score.token_content_precision,
            token_content_f1=score.token_content_f1,
            token_order_preservation=score.token_order_preservation,
            legal_critical_recall=score.legal_critical_recall,
            reference_reliable=bool(case["reference_reliable"]),
            error=None,
        )
        case_output = result_root / sample_id
        case_output.mkdir(parents=True, exist_ok=True)
        (case_output / "model-output.txt").write_text(
            raw_text,
            encoding="utf-8",
        )
        (case_output / "metrics.json").write_text(
            json.dumps(
                asdict(result),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = ModelPageResult(
            sample_id=sample_id,
            object_key=str(case["object_key"]),
            page_index=int(case["page_index"]),
            gold_source=str(case["gold_source"]),
            model=MODEL,
            routed_provider="",
            input_tokens=None,
            output_tokens=None,
            thinking_tokens=None,
            total_tokens=None,
            cost_usd=None,
            latency_ms=latency_ms,
            retry_count=retry_count,
            character_error_rate=None,
            word_error_rate=None,
            token_content_recall=None,
            token_content_precision=None,
            token_content_f1=None,
            token_order_preservation=None,
            legal_critical_recall=None,
            reference_reliable=bool(case["reference_reliable"]),
            error=f"{type(exc).__name__}: {exc}",
        )
        case_output = result_root / sample_id
        case_output.mkdir(parents=True, exist_ok=True)
        (case_output / "model-output.txt").write_text(
            "",
            encoding="utf-8",
        )
        (case_output / "metrics.json").write_text(
            json.dumps(
                asdict(result),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return result


def _mean_optional(
    values: list[int | float | None],
) -> float | None:
    observed = [
        float(value)
        for value in values
        if value is not None
    ]
    return mean(observed) if observed else None


def _run_model() -> int:
    manifest = json.loads(
        PREPARED_MANIFEST.read_text(encoding="utf-8")
    )
    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("prepared manifest has no cases")

    prepared_root = PREPARED_MANIFEST.parent
    result_root = OUTPUT / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    provider = _provider()
    workers = min(MAX_CONCURRENCY, len(cases))
    if workers < 1:
        raise ValueError("SCJ_VISUAL_MAX_CONCURRENCY must be positive")

    results: list[ModelPageResult] = []
    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _run_one,
                provider=provider,
                prepared_root=prepared_root,
                case=case,
                result_root=result_root,
            )
            for case in cases
        ]
        for future in as_completed(futures):
            results.append(future.result())
    wall_ms = int((time.perf_counter() - wall_started) * 1000)
    results.sort(key=lambda result: result.sample_id)

    completed = [
        result
        for result in results
        if result.error is None
    ]
    costs = [
        result.cost_usd
        for result in completed
        if result.cost_usd is not None
    ]
    report = {
        "schema_version": 1,
        "benchmark_kind": "full_page_visual_transcription",
        "model": MODEL,
        "reasoning_effort": REASONING,
        "provider_order": list(PROVIDER_ORDER),
        "prompt": PROMPT,
        "token_limit": None,
        "cases": len(results),
        "completed": len(completed),
        "failed": len(results) - len(completed),
        "coverage": len(completed) / len(results),
        "api_wall_clock_ms": wall_ms,
        "throughput_pages_per_second": (
            len(results) / (wall_ms / 1000)
            if wall_ms
            else None
        ),
        "tokens": {
            "input_total": sum(
                result.input_tokens or 0
                for result in completed
            ),
            "output_total": sum(
                result.output_tokens or 0
                for result in completed
            ),
            "thinking_total": sum(
                result.thinking_tokens or 0
                for result in completed
            ),
            "total": sum(
                result.total_tokens or 0
                for result in completed
            ),
            "input_mean_per_page": _mean_optional(
                [result.input_tokens for result in completed]
            ),
            "output_mean_per_page": _mean_optional(
                [result.output_tokens for result in completed]
            ),
            "thinking_mean_per_page": _mean_optional(
                [result.thinking_tokens for result in completed]
            ),
        },
        "cost": {
            "total_usd": sum(costs),
            "mean_per_completed_page_usd": (
                sum(costs) / len(completed)
                if completed
                else None
            ),
        },
        "latency_ms": {
            "mean": _mean_optional(
                [result.latency_ms for result in completed]
            ),
            "min": (
                min(result.latency_ms for result in completed)
                if completed
                else None
            ),
            "max": (
                max(result.latency_ms for result in completed)
                if completed
                else None
            ),
        },
        "quality_vs_reference": {
            "mean_word_error_rate": _mean_optional(
                [result.word_error_rate for result in completed]
            ),
            "mean_character_error_rate": _mean_optional(
                [
                    result.character_error_rate
                    for result in completed
                ]
            ),
            "mean_token_content_f1": _mean_optional(
                [result.token_content_f1 for result in completed]
            ),
            "mean_order_preservation": _mean_optional(
                [
                    result.token_order_preservation
                    for result in completed
                ]
            ),
            "mean_legal_critical_recall": _mean_optional(
                [
                    result.legal_critical_recall
                    for result in completed
                ]
            ),
        },
        "reference_semantics": {
            "pdf_text_layer_is_authoritative_gold": False,
            "reference_status": "dual_channel_aligned",
            "purpose": (
                "Score against native text only after independent OCR of the "
                "exact rendered page agrees under the admission policy. "
                "The preserved image remains the primary human-auditable "
                "evidence for adjudicating material discrepancies."
            ),
        },
        "records": [asdict(result) for result in results],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "records.jsonl").write_text(
        "".join(
            json.dumps(
                asdict(result),
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for result in results
        ),
        encoding="utf-8",
    )
    summary = (
        f"## {MODEL}\n\n"
        f"- Pages: {len(completed)}/{len(results)}\n"
        f"- Wall clock: {wall_ms} ms\n"
        f"- Mean latency/page: {report['latency_ms']['mean']} ms\n"
        f"- Cost total: ${report['cost']['total_usd']:.8f}\n"
        f"- Mean WER vs reference: {report['quality_vs_reference']['mean_word_error_rate']}\n"
        f"- Mean legal-critical recall vs reference: "
        f"{report['quality_vs_reference']['mean_legal_critical_recall']}\n"
        f"- Tokens in/out/thinking: "
        f"{report['tokens']['input_total']} / "
        f"{report['tokens']['output_total']} / "
        f"{report['tokens']['thinking_total']}\n"
    )
    (OUTPUT / "summary.md").write_text(
        summary,
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "model": MODEL,
                "completed": len(completed),
                "failed": len(results) - len(completed),
                "cost_usd": report["cost"]["total_usd"],
                "wall_ms": wall_ms,
            },
            sort_keys=True,
        )
    )
    return 0 if len(completed) == len(results) else 1


def main() -> int:
    if STAGE == "prepare":
        return _prepare()
    if STAGE == "run":
        return _run_model()
    raise ValueError("SCJ_VISUAL_STAGE must be prepare or run")


if __name__ == "__main__":
    raise SystemExit(main())
