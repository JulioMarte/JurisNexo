from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.decision_batching import (
    DecisionBatchPolicy,
    DecisionRecord,
)
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.jev_claims import (
    EvidenceClaim,
    evaluate_claim_support_batch,
)
from jurisnexo.normalization.jev_calibration import (
    BinaryRoutingObservation,
    brier_score,
    evaluate_frozen_candidate_on_holdout,
    select_candidate_threshold,
)

PREFIX = "jurisdictions/do/scj/principales-sentencias/"
OUTPUT = Path(
    os.environ.get(
        "JEV_PRINCIPALES_BENCHMARK_OUTPUT",
        ".artifacts/jev-principales-benchmark.json",
    )
)
SOURCE_CASES = int(os.environ.get("JEV_PRINCIPALES_SOURCE_CASES", "4"))
EXCERPT_CHARS = int(os.environ.get("JEV_PRINCIPALES_EXCERPT_CHARS", "3500"))
MAX_COST_USD = float(
    os.environ.get("JEV_PRINCIPALES_MAX_COST_USD", "0.003")
)

_IDENTIFIER_PATTERNS = (
    re.compile(r"SCJ-[A-Z0-9-]{4,}", re.IGNORECASE),
    re.compile(
        r"\b(?:expediente|sentencia)\s*"
        r"(?:núm\.?|n[oú]m(?:ero)?\.?|no\.)?\s*[:.-]?\s*"
        r"([A-Z0-9./-]{4,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bart(?:í|i)culo\s+(\d+(?:[.-]\d+)*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bley\s+(?:núm(?:ero)?\.?\s*)?(\d+[\d-]*)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, slots=True)
class LabeledQualityRecord:
    record_id: str
    expected_corrupted: bool
    source_key: str
    text: str


@dataclass(frozen=True, slots=True)
class QualityMetric:
    record_id: str
    expected_corrupted: bool
    acceptable_probability: float
    material_error_probability: float
    uncertain_probability: float
    legal_critical_damage_probability: float
    needs_visual_review_probability: float


@dataclass(frozen=True, slots=True)
class ClaimMetric:
    claim_id: str
    expected: str
    support_probability: float
    contradiction_probability: float
    insufficient_probability: float


def _list_pdf_keys(store: Any) -> tuple[str, ...]:
    response = store.client.list_objects_v2(
        Bucket=store.config.bucket,
        Prefix=PREFIX,
        MaxKeys=100,
    )
    return tuple(
        sorted(
            str(item.get("Key") or "")
            for item in response.get("Contents", [])
            if str(item.get("Key") or "").endswith(".pdf")
        )
    )


def _download(store: Any, key: str) -> bytes:
    response = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )
    payload = response["Body"].read()
    return payload if isinstance(payload, bytes) else bytes(payload)


def _native_excerpt(pdf_bytes: bytes) -> str:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        parts: list[str] = []
        for page_index in range(min(len(document), 3)):
            page = document[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range().strip()
                finally:
                    text_page.close()
                if text:
                    parts.append(text)
                joined = "\n".join(parts)
                if len(joined) >= EXCERPT_CHARS:
                    return joined[:EXCERPT_CHARS]
            finally:
                page.close()
        return "\n".join(parts)[:EXCERPT_CHARS]
    finally:
        document.close()


def _visible_corruption(text: str) -> str:
    for pattern in _IDENTIFIER_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        start, end = match.span()
        token = text[start:end]
        chars = list(token)
        for index in range(len(chars) - 1, -1, -1):
            if chars[index].isdigit():
                chars[index] = "�"
                return text[:start] + "".join(chars) + text[end:]

    words = re.finditer(r"\b[A-Za-zÁÉÍÓÚáéíóúÑñ]{8,}\b", text)
    match = next(words, None)
    if match is None:
        raise RuntimeError("could not create visible corruption")
    token = match.group(0)
    midpoint = len(token) // 2
    corrupted = token[:midpoint] + "�" + token[midpoint + 1 :]
    return text[: match.start()] + corrupted + text[match.end() :]


def _extract_identifier(text: str) -> str | None:
    for pattern in _IDENTIFIER_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        return match.group(1) if match.lastindex else match.group(0)
    return None


def _wrong_value(value: str) -> str:
    chars = list(value)
    for index in range(len(chars) - 1, -1, -1):
        if chars[index].isdigit():
            chars[index] = "9" if chars[index] != "9" else "8"
            return "".join(chars)
    return value + "-X"


def _argmax_claim(metric: ClaimMetric) -> str:
    candidates = {
        "supported": metric.support_probability,
        "contradicted": metric.contradiction_probability,
        "insufficient": metric.insufficient_probability,
    }
    return max(candidates, key=candidates.__getitem__)


def _split_record_id(record_id: str) -> str:
    match = re.match(r"case_(\d+)_", record_id)
    if match is None:
        raise ValueError(f"unexpected benchmark record id: {record_id}")
    case_number = int(match.group(1))
    return "calibration" if case_number % 2 == 1 else "holdout"


def main() -> int:
    if not 2 <= SOURCE_CASES <= 8:
        raise ValueError(
            "JEV_PRINCIPALES_SOURCE_CASES must be between 2 and 8"
        )
    if not 1000 <= EXCERPT_CHARS <= 6000:
        raise ValueError(
            "JEV_PRINCIPALES_EXCERPT_CHARS must be between 1000 and 6000"
        )
    if not 0 < MAX_COST_USD <= 0.01:
        raise ValueError("JEV benchmark cost cap must be > 0 and <= 0.01")

    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for JEV benchmark")

    provider = OpenRouterDecisionProvider(
        api_key=settings.api_key.get_secret_value(),
        model=models.jev_model,
    )
    store = build_s3_object_store()
    keys = _list_pdf_keys(store)
    if len(keys) < SOURCE_CASES:
        raise RuntimeError(
            f"expected at least {SOURCE_CASES} Principales PDFs, found {len(keys)}"
        )

    labeled: list[LabeledQualityRecord] = []
    claims: list[EvidenceClaim] = []
    claim_expectations: dict[str, str] = {}

    for case_index, key in enumerate(keys[:SOURCE_CASES], start=1):
        excerpt = _native_excerpt(_download(store, key))
        if len(excerpt) < 1000:
            raise RuntimeError(
                f"Principales case {key} has insufficient native text "
                "for JEV benchmark"
            )

        clean_id = f"case_{case_index}_clean"
        corrupt_id = f"case_{case_index}_corrupt"
        labeled.extend(
            (
                LabeledQualityRecord(clean_id, False, key, excerpt),
                LabeledQualityRecord(
                    corrupt_id,
                    True,
                    key,
                    _visible_corruption(excerpt),
                ),
            )
        )

        identifier = _extract_identifier(excerpt)
        if identifier is not None:
            supported_id = f"case_{case_index}_claim_supported"
            contradicted_id = f"case_{case_index}_claim_contradicted"
            claims.extend(
                (
                    EvidenceClaim(
                        claim_id=supported_id,
                        evidence=excerpt,
                        proposed_value=identifier,
                        field_name="legal_identifier",
                    ),
                    EvidenceClaim(
                        claim_id=contradicted_id,
                        evidence=excerpt,
                        proposed_value=_wrong_value(identifier),
                        field_name="legal_identifier",
                    ),
                )
            )
            claim_expectations[supported_id] = "supported"
            claim_expectations[contradicted_id] = "contradicted"

    quality_evaluator = JevBatchQualityEvaluator(
        provider=provider,
        policy=DecisionBatchPolicy(
            max_context_tokens=32_000,
            target_total_tokens=24_000,
            reserved_instruction_tokens=4_000,
            max_records_per_batch=20,
        ),
    )
    quality_result = quality_evaluator.evaluate(
        records=tuple(
            DecisionRecord(
                record_id=item.record_id,
                text=item.text,
                metadata={
                    "source": "SCJ",
                    "collection": "principales-sentencias",
                    "expected_corrupted": item.expected_corrupted,
                },
            )
            for item in labeled
        ),
        state_description=(
            "Records are source-derived SCJ Principales text excerpts. Some were "
            "left untouched and some contain a controlled visible transcription "
            "corruption. Judge only observable transcription quality."
        ),
    )
    quality_by_id = {
        item.record_id: item.probabilities
        for item in quality_result.records
    }
    quality_metrics = tuple(
        QualityMetric(
            record_id=item.record_id,
            expected_corrupted=item.expected_corrupted,
            acceptable_probability=quality_by_id[item.record_id].acceptable,
            material_error_probability=(
                quality_by_id[item.record_id].material_error
            ),
            uncertain_probability=quality_by_id[item.record_id].uncertain,
            legal_critical_damage_probability=(
                quality_by_id[item.record_id].legal_critical_damage
            ),
            needs_visual_review_probability=(
                quality_by_id[item.record_id].needs_visual_review
            ),
        )
        for item in labeled
    )

    claim_evaluation = evaluate_claim_support_batch(
        provider,
        claims=tuple(claims),
    )
    claim_metrics = tuple(
        ClaimMetric(
            claim_id=item.claim_id,
            expected=claim_expectations[item.claim_id],
            support_probability=item.support_probability,
            contradiction_probability=item.contradiction_probability,
            insufficient_probability=item.insufficient_probability,
        )
        for item in claim_evaluation.decisions
    )

    thresholds = (0.25, 0.50, 0.75)
    calibration_quality = tuple(
        item
        for item in quality_metrics
        if _split_record_id(item.record_id) == "calibration"
    )
    holdout_quality = tuple(
        item
        for item in quality_metrics
        if _split_record_id(item.record_id) == "holdout"
    )
    calibration_observations = tuple(
        BinaryRoutingObservation(
            record_id=item.record_id,
            expected_positive=item.expected_corrupted,
            probability=item.material_error_probability,
        )
        for item in calibration_quality
    )
    holdout_observations = tuple(
        BinaryRoutingObservation(
            record_id=item.record_id,
            expected_positive=item.expected_corrupted,
            probability=item.material_error_probability,
        )
        for item in holdout_quality
    )
    candidate = select_candidate_threshold(
        calibration_observations,
        thresholds=thresholds,
    )
    candidate_holdout = evaluate_frozen_candidate_on_holdout(
        candidate,
        holdout_observations,
    )
    calibration_threshold_metrics = {
        str(threshold): asdict(
            select_candidate_threshold(
                calibration_observations,
                thresholds=(threshold,),
            ).calibration
        )
        for threshold in thresholds
    }
    holdout_threshold_metrics = {
        str(threshold): asdict(
            evaluate_frozen_candidate_on_holdout(
                select_candidate_threshold(
                    calibration_observations,
                    thresholds=(threshold,),
                ),
                holdout_observations,
            )
        )
        for threshold in thresholds
    }

    binary_brier = brier_score(
        tuple(
            BinaryRoutingObservation(
                record_id=item.record_id,
                expected_positive=item.expected_corrupted,
                probability=item.material_error_probability,
            )
            for item in quality_metrics
        )
    )

    claim_accuracy = (
        sum(_argmax_claim(item) == item.expected for item in claim_metrics)
        / len(claim_metrics)
        if claim_metrics
        else 0.0
    )

    quality_cost = sum(
        batch.cost_usd or 0.0
        for batch in quality_result.batches
    )
    claim_cost = sum(
        telemetry.cost_usd or 0.0
        for telemetry in claim_evaluation.telemetry
    )
    total_cost = quality_cost + claim_cost
    if total_cost > MAX_COST_USD:
        raise RuntimeError(
            f"JEV benchmark exceeded cost cap: {total_cost:.6f} USD"
        )

    payload = {
        "schema_version": 1,
        "model": models.jev_model,
        "source_case_count": SOURCE_CASES,
        "quality_record_count": len(quality_metrics),
        "claim_record_count": len(claim_metrics),
        "context_policy": {
            "max_context_tokens": 32_000,
            "target_total_tokens": 24_000,
            "reserved_instruction_tokens": 4_000,
        },
        "quality_batch_telemetry": [
            asdict(batch) for batch in quality_result.batches
        ],
        "quality_metrics": [asdict(item) for item in quality_metrics],
        "calibration_threshold_metrics": calibration_threshold_metrics,
        "holdout_threshold_metrics": holdout_threshold_metrics,
        "calibration_record_count": len(calibration_quality),
        "holdout_record_count": len(holdout_quality),
        "candidate_material_error_threshold": candidate.threshold,
        "candidate_calibration_metrics": asdict(candidate.calibration),
        "candidate_holdout_metrics": asdict(candidate_holdout),
        "material_error_brier_score": binary_brier,
        "claim_metrics": [asdict(item) for item in claim_metrics],
        "claim_argmax_accuracy": claim_accuracy,
        "claim_telemetry": [
            asdict(item) for item in claim_evaluation.telemetry
        ],
        "observed_quality_cost_usd": quality_cost,
        "observed_claim_cost_usd": claim_cost,
        "observed_total_cost_usd": total_cost,
        "limitations": [
            (
                "Visible-corruption routing measures text-observable damage only. "
                "JEV cannot know that a plausible identifier is wrong without reference."
            ),
            (
                "Claim verification supplies evidence and therefore measures a "
                "different capability from transcription-quality routing."
            ),
            (
                "Calibration and holdout are deterministically separated. This "
                "bounded benchmark is still not sufficient by itself to promote "
                "JEV from shadow to active production routing."
            ),
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
