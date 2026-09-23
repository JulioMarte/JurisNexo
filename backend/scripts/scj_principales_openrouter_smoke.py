from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.quality import (
    assess_text_quality,
    extract_text_from_structural_json,
)

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "benchmark" / "normalization"),
)
from scj_page_selection import (  # noqa: E402
    has_native_text,
    select_reference_page,
)

OUT = Path(
    os.environ.get(
        "SCJ_PRINCIPALES_OPENROUTER_OUTPUT",
        "scj-principales-openrouter-smoke-output",
    )
)
LIMIT = int(os.environ.get("SCJ_PRINCIPALES_OPENROUTER_LIMIT", "2"))
TEXT_LIMIT = int(os.environ.get("SCJ_PRINCIPALES_OPENROUTER_TEXT_CHARS", "5000"))
MAX_COST_USD = float(
    os.environ.get("SCJ_PRINCIPALES_OPENROUTER_MAX_COST_USD", "0.01")
)
DEEPSEEK_THINKING = os.environ.get(
    "SCJ_PRINCIPALES_OPENROUTER_DEEPSEEK_THINKING", "none"
)
PREFIX = "jurisdictions/do/scj/principales-sentencias/"


@dataclass(frozen=True, slots=True)
class ModelObservation:
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    requested_reasoning_effort: str
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreparedCase:
    record_id: str
    object_key: str
    source_sha256: str
    source_bytes: int
    normalized_chars: int
    excerpt: str
    deterministic_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SmokeCase:
    object_key: str
    source_sha256: str
    source_bytes: int
    normalized_chars: int
    excerpt_chars: int
    deterministic_flags: tuple[str, ...]
    jev_answers: dict[str, Any]
    deepseek: ModelObservation | None
    deepseek_error: str | None = None


def _deepseek_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "escalate": {"type": "boolean"},
            "risk": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
        },
        "required": ["escalate", "risk", "reasons"],
        "additionalProperties": False,
    }


def _deepseek_observation(
    result: Any,
    *,
    latency_ms: int,
    reasoning_effort: str,
) -> ModelObservation:
    return ModelObservation(
        model=result.model,
        provider=result.provider,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        thinking_tokens=result.usage.thinking_tokens,
        cost_usd=result.cost_usd,
        latency_ms=latency_ms,
        requested_reasoning_effort=reasoning_effort,
        value=dict(result.value),
    )


def _listed_principales_keys(store: Any) -> tuple[str, ...]:
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
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if key.endswith(".pdf"):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError(
                "S3 listing was truncated without continuation token"
            )
    return tuple(sorted(keys))


def _download(store: Any, object_key: str) -> bytes:
    response = store.client.get_object(
        Bucket=store.config.bucket,
        Key=object_key,
    )
    payload = response["Body"].read()
    return payload if isinstance(payload, bytes) else bytes(payload)


def _single_page_pdf(pdf_bytes: bytes, page_index: int) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    output = io.BytesIO()
    writer.write(output)
    payload = output.getvalue()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError("single-page PDF extraction did not produce a PDF")
    return payload


def _prepare_cases(
    *,
    store: Any,
    normalizer: DoclingStructuralNormalizer,
    object_keys: tuple[str, ...],
    limit: int,
) -> tuple[PreparedCase, ...]:
    prepared: list[PreparedCase] = []
    for object_key in object_keys:
        if len(prepared) >= limit:
            break
        source = _download(store, object_key)
        if not has_native_text(source):
            continue
        selected = select_reference_page(
            source,
            min_reference_chars=800,
            max_pages_to_scan=120,
        )
        if selected is None:
            continue
        page_pdf = _single_page_pdf(source, selected.page_index)
        normalized = normalizer.normalize(
            page_pdf,
            FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            filename=f"{object_key.rsplit('/', 1)[-1]}-p{selected.page_index + 1}.pdf",
        )
        text = extract_text_from_structural_json(normalized.payload)
        excerpt = text[:TEXT_LIMIT]
        if not excerpt.strip():
            continue
        deterministic = assess_text_quality(excerpt)
        prepared.append(
            PreparedCase(
                record_id=f"case_{len(prepared) + 1}",
                object_key=object_key,
                source_sha256=hashlib.sha256(source).hexdigest(),
                source_bytes=len(source),
                normalized_chars=len(text),
                excerpt=excerpt,
                deterministic_flags=deterministic.risk_flags,
            )
        )
    return tuple(prepared)


def _jev_questions(cases: tuple[PreparedCase, ...]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for item in cases:
        prefix = item.record_id
        questions[f"{prefix}__transcription_quality"] = {
            "type": "choice",
            "instructions": (
                f'For the record with id "{prefix}", classify whether the normalized '
                "legal text is usable as evidence. Judge transcription fidelity only, "
                "not the legal merits."
            ),
            "criteria": {
                "acceptable": (
                    "Text appears materially faithful and readable; no visible pattern "
                    "suggests missing or corrupted legally important content."
                ),
                "material_error": (
                    "Text shows likely corruption, omissions, broken numbering, or "
                    "damage that could change legally important meaning."
                ),
                "uncertain": (
                    "The excerpt does not provide enough evidence to confidently choose "
                    "acceptable or material_error."
                ),
            },
        }
        questions[f"{prefix}__legal_critical_damage"] = {
            "type": "noul",
            "instructions": (
                f'For the record with id "{prefix}", decide whether transcription '
                "damage appears to affect legally critical tokens."
            ),
            "true_when": (
                "Damage appears to affect names, dates, case numbers, article/law "
                "numbers, monetary amounts, citations, holdings, or dispositive text."
            ),
            "false_when": (
                "No such legally critical transcription damage is apparent."
            ),
        }
        questions[f"{prefix}__needs_visual_review"] = {
            "type": "noul",
            "instructions": (
                f'For the record with id "{prefix}", decide whether comparison against '
                "the original rendered page is warranted before accepting the text."
            ),
            "true_when": (
                "There is material uncertainty, suspicious corruption, or legally "
                "critical ambiguity that text-only checks cannot safely resolve."
            ),
            "false_when": (
                "The normalized text is sufficiently clear that visual escalation is "
                "not warranted."
            ),
        }
    return questions


def _answers_for_case(
    answers: dict[str, dict[str, Any]],
    *,
    record_id: str,
) -> dict[str, Any]:
    prefix = f"{record_id}__"
    return {
        key.removeprefix(prefix): value
        for key, value in answers.items()
        if key.startswith(prefix)
    }


def main() -> int:
    if LIMIT < 1 or LIMIT > 2:
        raise ValueError(
            "SCJ_PRINCIPALES_OPENROUTER_LIMIT must be between 1 and 2"
        )
    if TEXT_LIMIT < 500 or TEXT_LIMIT > 5000:
        raise ValueError(
            "SCJ_PRINCIPALES_OPENROUTER_TEXT_CHARS must be between 500 and 5000"
        )
    if MAX_COST_USD <= 0 or MAX_COST_USD > 0.02:
        raise ValueError(
            "SCJ_PRINCIPALES_OPENROUTER_MAX_COST_USD must be > 0 and <= 0.02"
        )

    openrouter = get_openrouter_settings()
    if openrouter.api_key is None:
        raise RuntimeError(
            "OPENROUTER_API_KEY is required for this explicit live smoke"
        )
    models = get_normalization_model_settings()
    api_key = openrouter.api_key.get_secret_value()

    jev_provider = OpenRouterDecisionProvider(
        api_key=api_key,
        model=models.jev_model,
    )
    deepseek_provider = OpenRouterStructuredModelProvider(
        api_key=api_key,
        model=models.deepseek_model,
        base_url=openrouter.base_url,
    )
    normalizer = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
        pdf_aware_ocr=True,
    )
    store = build_s3_object_store()

    all_keys = _listed_principales_keys(store)
    if len(all_keys) < LIMIT:
        raise RuntimeError(
            f"expected at least {LIMIT} Principales PDFs in S3, found {len(all_keys)}"
        )

    prepared = _prepare_cases(
        store=store,
        normalizer=normalizer,
        object_keys=all_keys,
        limit=LIMIT,
    )
    if len(prepared) < LIMIT:
        raise RuntimeError(
            f"only {len(prepared)} Principales volumes exposed a "
            "native-text judgment page"
        )

    jev_started = time.perf_counter()
    jev_result = jev_provider.decide(
        state_description=(
            "Each record is a normalized text excerpt from an official SCJ "
            "Principales sentence. Decisions concern transcription quality only."
        ),
        records=tuple(
            {"id": item.record_id, "record": item.excerpt}
            for item in prepared
        ),
        questions=_jev_questions(prepared),
    )
    jev_latency_ms = int((time.perf_counter() - jev_started) * 1000)
    running_cost = jev_result.cost_usd or 0.0
    if running_cost > MAX_COST_USD:
        raise RuntimeError(
            f"live smoke exceeded cost cap after JEV: ${running_cost:.6f}"
        )

    results: list[SmokeCase] = []
    provider_errors: list[str] = []
    for item in prepared:
        deepseek_started = time.perf_counter()
        deepseek_result = None
        deepseek_observation: ModelObservation | None = None
        deepseek_error: str | None = None
        try:
            deepseek_result = deepseek_provider.generate_structured(
                prompt=(
                    "You are a conservative extraction-quality challenger. Inspect "
                    "only the normalized legal-text excerpt below for signs of "
                    "parser/OCR damage such as broken numbering, garbled characters, "
                    "fragmented words, or materially suspicious omissions. Do not "
                    "evaluate the legal merits. Return whether this excerpt should "
                    "be escalated for human/visual review.\n\nExcerpt:\n"
                    + item.excerpt
                ),
                json_schema=_deepseek_schema(),
                max_output_tokens=1500,
                thinking_level=DEEPSEEK_THINKING,
            )
        except ModelProviderError as exc:
            deepseek_error = str(exc)
            provider_errors.append(f"{item.record_id}: {exc}")
        deepseek_latency_ms = int(
            (time.perf_counter() - deepseek_started) * 1000
        )
        if deepseek_result is not None:
            deepseek_observation = _deepseek_observation(
                deepseek_result,
                latency_ms=deepseek_latency_ms,
                reasoning_effort=DEEPSEEK_THINKING,
            )
            running_cost += deepseek_observation.cost_usd or 0.0
        if running_cost > MAX_COST_USD:
            raise RuntimeError(
                f"live smoke exceeded cost cap after DeepSeek: ${running_cost:.6f}"
            )
        results.append(
            SmokeCase(
                object_key=item.object_key,
                source_sha256=item.source_sha256,
                source_bytes=item.source_bytes,
                normalized_chars=item.normalized_chars,
                excerpt_chars=len(item.excerpt),
                deterministic_flags=item.deterministic_flags,
                jev_answers=_answers_for_case(
                    jev_result.answers,
                    record_id=item.record_id,
                ),
                deepseek=deepseek_observation,
                deepseek_error=deepseek_error,
            )
        )

    jev_batch = ModelObservation(
        model=jev_result.model,
        provider=jev_result.provider,
        input_tokens=jev_result.usage.input_tokens,
        output_tokens=jev_result.usage.output_tokens,
        thinking_tokens=None,
        cost_usd=jev_result.cost_usd,
        latency_ms=jev_latency_ms,
        requested_reasoning_effort="decisions",
        value={"answers": jev_result.answers},
    )
    payload = {
        "schema_version": 2,
        "source": "scj",
        "collection": "principales-sentencias",
        "runtime_status": (
            "ok" if not provider_errors else "provider_structured_output_failed"
        ),
        "provider_errors": provider_errors,
        "case_count": len(results),
        "model_call_count": 1 + len(results),
        "jev_batch": asdict(jev_batch),
        "deepseek_model": models.deepseek_model,
        "deepseek_structured_thinking": DEEPSEEK_THINKING,
        "text_char_limit_per_case": TEXT_LIMIT,
        "max_cost_usd": MAX_COST_USD,
        "observed_cost_usd": running_cost,
        "cases": [asdict(item) for item in results],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(
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
    return 1 if provider_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
