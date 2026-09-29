"""Use JEV as a probabilistic auditor for OCR/native-text discrepancies.

This stage consumes only deterministic review candidates. It never mutates
canonical text. Recommendations are persisted as evidence and remain shadow
until a separately calibrated promotion policy is explicitly enabled.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

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
from jurisnexo.normalization.jev_quality import JevRoutingPolicy

MAX_CONTEXT_CHARS_PER_RECORD = 7000


def _record_id(item: dict[str, object]) -> str:
    source_sha = str(item["source_pdf_sha256"])
    page_index = int(item["page_index"])
    return f"{source_sha[:16]}-p{page_index:06d}"


def _render_state(item: dict[str, object]) -> str:
    metrics = {
        "classification": item.get("classification"),
        "risk_reasons": item.get("risk_reasons"),
        "native_characters": item.get("native_characters"),
        "ocr_characters": item.get("ocr_characters"),
        "ocr_mean_confidence": item.get("ocr_mean_confidence"),
        "ocr_median_confidence": item.get("ocr_median_confidence"),
        "ocr_p10_confidence": item.get("ocr_p10_confidence"),
        "ocr_low_confidence_word_ratio": item.get("ocr_low_confidence_word_ratio"),
        "embedded_image_count": item.get("embedded_image_count"),
        "alignment_assessment": item.get("assessment"),
    }
    segments = item.get("diff_segments")
    if not isinstance(segments, list):
        segments = []
    payload = {
        "metrics": metrics,
        "disagreement_segments": segments,
        "instruction": (
            "Judge transcription quality and escalation need only. The native PDF "
            "text and OCR are independent observations; neither is guaranteed to "
            "be ground truth. Do not infer legal merits."
        ),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return text[:MAX_CONTEXT_CHARS_PER_RECORD]


def load_candidates(path: Path, *, limit: int | None = None) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise RuntimeError("JEV candidate line is not an object")
        items.append(item)
        if limit is not None and len(items) >= limit:
            break
    return items


def run(
    *,
    input_path: Path,
    output: Path,
    max_cost_usd: float,
    limit: int | None,
) -> int:
    if not 0 < max_cost_usd <= 1.0:
        raise ValueError("max_cost_usd must be > 0 and <= 1.0")

    candidates = load_candidates(input_path, limit=limit)
    output.mkdir(parents=True, exist_ok=True)
    if not candidates:
        (output / "jev-decisions.jsonl").write_text("", encoding="utf-8")
        (output / "deepseek-review.jsonl").write_text("", encoding="utf-8")
        (output / "visual-review-after-jev.jsonl").write_text("", encoding="utf-8")
        (output / "summary.json").write_text(
            json.dumps(
                {"schema_version": 1, "candidate_count": 0, "observed_cost_usd": 0.0},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0

    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for JEV triage")

    provider = OpenRouterDecisionProvider(
        api_key=settings.api_key.get_secret_value(),
        model=models.jev_model,
        base_url=settings.decisions_base_url,
    )
    evaluator = JevBatchQualityEvaluator(
        provider=provider,
        policy=DecisionBatchPolicy(
            max_context_tokens=32_000,
            target_total_tokens=24_000,
            reserved_instruction_tokens=4_000,
            max_records_per_batch=20,
        ),
    )
    records = tuple(
        DecisionRecord(
            record_id=_record_id(item),
            text=_render_state(item),
            metadata={
                "source_pdf_sha256": str(item["source_pdf_sha256"]),
                "page_index": int(item["page_index"]),
                "deterministic_classification": str(item.get("classification") or ""),
                "deterministic_route": str(item.get("quality_route") or ""),
            },
        )
        for item in candidates
    )
    evaluation = evaluator.evaluate(
        records=records,
        state_description=(
            "These records summarize independent native-PDF-text versus rendered-page "
            "Tesseract OCR discrepancies for Dominican SCJ pages. Decide whether the "
            "text is acceptable, materially damaged, legally critical, or requires "
            "visual review. Native text is not assumed to be ground truth."
        ),
    )
    by_id = {item.record_id: item.probabilities for item in evaluation.records}
    policy = JevRoutingPolicy(promotion_state="shadow")
    decisions: list[dict[str, object]] = []
    deepseek: list[dict[str, object]] = []
    visual: list[dict[str, object]] = []

    for candidate in candidates:
        rid = _record_id(candidate)
        probabilities = by_id[rid]
        recommendation = policy.recommend(probabilities)
        decision = {
            "schema_version": 1,
            "record_id": rid,
            "source_pdf_sha256": candidate["source_pdf_sha256"],
            "page_index": candidate["page_index"],
            "deterministic_classification": candidate.get("classification"),
            "deterministic_route": candidate.get("quality_route"),
            "jev_model": models.jev_model,
            "jev_probabilities": asdict(probabilities),
            "jev_recommendation": recommendation,
            "effective_action": policy.route(probabilities),
            "runtime_policy": "shadow",
        }
        decisions.append(decision)
        enriched = {**candidate, "jev": decision}
        if recommendation in {"deepseek_review", "human_review"}:
            deepseek.append(enriched)
        if recommendation in {"visual_review", "human_review"}:
            visual.append(enriched)

    observed_cost = sum(batch.cost_usd or 0.0 for batch in evaluation.batches)
    if observed_cost > max_cost_usd:
        raise RuntimeError(
            f"JEV triage exceeded configured cost cap: {observed_cost:.6f} USD"
        )

    def write_jsonl(name: str, items: list[dict[str, object]]) -> None:
        (output / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items),
            encoding="utf-8",
        )

    write_jsonl("jev-decisions.jsonl", decisions)
    write_jsonl("deepseek-review.jsonl", deepseek)
    write_jsonl("visual-review-after-jev.jsonl", visual)
    summary = {
        "schema_version": 1,
        "candidate_count": len(candidates),
        "jev_model": models.jev_model,
        "runtime_policy": "shadow",
        "deepseek_review_candidates": len(deepseek),
        "visual_review_candidates": len(visual),
        "observed_cost_usd": observed_cost,
        "max_cost_usd": max_cost_usd,
        "batch_telemetry": [asdict(batch) for batch in evaluation.batches],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    return run(
        input_path=args.input,
        output=args.output,
        max_cost_usd=args.max_cost_usd,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
