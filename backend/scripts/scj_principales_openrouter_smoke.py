from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.judges import StructuredTextQualityJudge
from jurisnexo.normalization.quality import (
    assess_text_quality,
    extract_text_from_structural_json,
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
PREFIX = "jurisdictions/do/scj/principales-sentencias/"


@dataclass(frozen=True, slots=True)
class ModelObservation:
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SmokeCase:
    object_key: str
    source_sha256: str
    source_bytes: int
    normalized_chars: int
    excerpt_chars: int
    deterministic_flags: tuple[str, ...]
    jev: ModelObservation
    deepseek: ModelObservation


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


def _observation(result: Any) -> ModelObservation:
    return ModelObservation(
        model=result.model,
        provider=result.provider,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=result.cost_usd,
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

    jev_provider = OpenRouterStructuredModelProvider(
        api_key=api_key,
        model=models.jev_model,
        base_url=openrouter.base_url,
    )
    deepseek_provider = OpenRouterStructuredModelProvider(
        api_key=api_key,
        model=models.deepseek_model,
        base_url=openrouter.base_url,
    )
    jev = StructuredTextQualityJudge(jev_provider)
    normalizer = DoclingStructuralNormalizer()
    store = build_s3_object_store()

    all_keys = _listed_principales_keys(store)
    if len(all_keys) < LIMIT:
        raise RuntimeError(
            f"expected at least {LIMIT} Principales PDFs in S3, found {len(all_keys)}"
        )

    results: list[SmokeCase] = []
    running_cost = 0.0
    for object_key in all_keys[:LIMIT]:
        response = store.client.get_object(
            Bucket=store.config.bucket,
            Key=object_key,
        )
        source = response["Body"].read()
        if not isinstance(source, bytes):
            source = bytes(source)
        source_sha256 = hashlib.sha256(source).hexdigest()

        normalized = normalizer.normalize(
            source,
            FormatInspection(
                media_type="application/pdf",
                detected_format="application/pdf",
                metadata={},
            ),
            filename=object_key.rsplit("/", 1)[-1],
        )
        text = extract_text_from_structural_json(normalized.payload)
        excerpt = text[:TEXT_LIMIT]
        deterministic = assess_text_quality(excerpt)

        jev_raw = jev.judge(
            excerpt,
            context={
                "source": "SCJ",
                "collection": "principales-sentencias",
                "object_key": object_key,
                "mode": "shadow-router-smoke",
                "deterministic_risk_flags": list(
                    deterministic.risk_flags
                ),
            },
        )
        jev_observation = ModelObservation(
            model=str(jev_raw["model"]),
            provider=str(jev_raw["provider"]),
            input_tokens=(
                int(jev_raw["input_tokens"])
                if isinstance(jev_raw.get("input_tokens"), int)
                else None
            ),
            output_tokens=(
                int(jev_raw["output_tokens"])
                if isinstance(jev_raw.get("output_tokens"), int)
                else None
            ),
            cost_usd=(
                float(jev_raw["cost_usd"])
                if isinstance(jev_raw.get("cost_usd"), (int, float))
                else None
            ),
            value={
                "pass_text": bool(jev_raw["pass_text"]),
                "material_error_probability": float(
                    jev_raw["material_error_probability"]
                ),
                "reasons": list(jev_raw["reasons"]),
            },
        )
        running_cost += jev_observation.cost_usd or 0.0
        if running_cost > MAX_COST_USD:
            raise RuntimeError(
                f"live smoke exceeded cost cap after JEV: ${running_cost:.6f}"
            )

        deepseek_result = deepseek_provider.generate_structured(
            prompt=(
                "You are a conservative extraction-quality challenger. Inspect "
                "only the normalized legal-text excerpt below for signs of "
                "parser/OCR damage such as broken numbering, garbled characters, "
                "fragmented words, or materially suspicious omissions. Do not "
                "evaluate the legal merits. Return whether this excerpt should "
                "be escalated for human/visual review.\n\nExcerpt:\n"
                + excerpt
            ),
            json_schema=_deepseek_schema(),
            max_output_tokens=220,
            thinking_level="none",
        )
        deepseek_observation = _observation(deepseek_result)
        running_cost += deepseek_observation.cost_usd or 0.0
        if running_cost > MAX_COST_USD:
            raise RuntimeError(
                f"live smoke exceeded cost cap after DeepSeek: ${running_cost:.6f}"
            )

        results.append(
            SmokeCase(
                object_key=object_key,
                source_sha256=source_sha256,
                source_bytes=len(source),
                normalized_chars=len(text),
                excerpt_chars=len(excerpt),
                deterministic_flags=deterministic.risk_flags,
                jev=jev_observation,
                deepseek=deepseek_observation,
            )
        )

    payload = {
        "schema_version": 1,
        "source": "scj",
        "collection": "principales-sentencias",
        "case_count": len(results),
        "model_call_count": len(results) * 2,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
