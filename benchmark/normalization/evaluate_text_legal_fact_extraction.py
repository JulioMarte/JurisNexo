from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.model_providers.openrouter import OpenRouterStructuredModelProvider
from jurisnexo.normalization.legal_fact_extraction import (
    LEGAL_FACT_FIELDS,
    LEGAL_FACT_SCHEMA,
    build_legal_fact_prompt,
    score_legal_fact_extraction,
    validate_legal_fact_payload,
)
from legal_fact_gold_v1 import extract_gold

DEFAULT_CONFIG = Path(
    "benchmark/normalization/scj_text_legal_fact_benchmark_v1.json"
)


@dataclass(frozen=True, slots=True)
class CorpusCase:
    sample_id: str
    split: str
    object_key: str
    page_index: int
    source_pdf_sha256: str
    reference_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedCase:
    case: CorpusCase
    text: str
    expected: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class RunConfig:
    model: str
    reasoning: str
    structured_mode: str
    provider_order: tuple[str, ...]
    max_output_tokens: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-call legal-fact extraction benchmark over frozen SCJ text gold."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("smoke", "calibration", "full"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning", default="high")
    parser.add_argument(
        "--structured-mode",
        choices=("tool", "json_schema", "json_object"),
        default="tool",
    )
    parser.add_argument("--provider-order", default="")
    parser.add_argument("--max-output-tokens", type=int, default=1800)
    parser.add_argument("--max-concurrency", type=int, default=8)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    return parser.parse_args()


def _load_cases(
    *,
    config_path: Path,
    prepared_root: Path,
) -> tuple[list[PreparedCase], dict[str, Any]]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = config["source_visual_benchmark"]
    manifest_path = prepared_root / "gold-benchmark-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases_raw = manifest.get("cases")
    if not isinstance(cases_raw, list):
        raise RuntimeError("prepared visual manifest has no cases array")
    if len(cases_raw) != int(source["expected_records"]):
        raise RuntimeError(
            "prepared visual corpus size drift: "
            f"expected {source['expected_records']}, got {len(cases_raw)}"
        )
    calibration_sources = set(config["calibration_source_pdf_sha256"])
    prepared: list[PreparedCase] = []
    split_sources: dict[str, set[str]] = {"calibration": set(), "holdout": set()}
    seen_ids: set[str] = set()
    for raw in cases_raw:
        if not isinstance(raw, dict):
            raise RuntimeError("prepared visual case is not an object")
        sample_id = str(raw["sample_id"])
        if sample_id in seen_ids:
            raise RuntimeError(f"duplicate sample id: {sample_id}")
        seen_ids.add(sample_id)
        source_sha = str(raw["source_pdf_sha256"])
        split = "calibration" if source_sha in calibration_sources else "holdout"
        split_sources[split].add(source_sha)
        if raw.get("reference_authority") != config["reference_authority"]:
            raise RuntimeError(f"unexpected reference authority for {sample_id}")
        reference_path = prepared_root / str(raw["reference_path"])
        text = reference_path.read_text(encoding="utf-8")
        reference_sha = str(raw["reference_sha256"])
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_sha != reference_sha:
            raise RuntimeError(
                f"native text digest drift for {sample_id}: "
                f"expected {reference_sha}, got {text_sha}"
            )
        case = CorpusCase(
            sample_id=sample_id,
            split=split,
            object_key=str(raw["object_key"]),
            page_index=int(raw["page_index"]),
            source_pdf_sha256=source_sha,
            reference_sha256=reference_sha,
        )
        prepared.append(
            PreparedCase(
                case=case,
                text=text,
                expected=validate_legal_fact_payload(extract_gold(text)),
            )
        )
    overlap = split_sources["calibration"] & split_sources["holdout"]
    if overlap:
        raise RuntimeError(f"source leakage across calibration/holdout: {sorted(overlap)}")
    calibration_count = sum(
        item.case.split == "calibration" for item in prepared
    )
    holdout_count = sum(item.case.split == "holdout" for item in prepared)
    if calibration_count != int(config["expected_calibration_records"]):
        raise RuntimeError(
            f"calibration count drift: expected {config['expected_calibration_records']}, "
            f"got {calibration_count}"
        )
    if holdout_count != int(config["expected_holdout_records"]):
        raise RuntimeError(
            f"holdout count drift: expected {config['expected_holdout_records']}, "
            f"got {holdout_count}"
        )
    return prepared, config


def _phase_cases(cases: list[PreparedCase], phase: str) -> list[PreparedCase]:
    calibration = [case for case in cases if case.case.split == "calibration"]
    if phase == "smoke":
        return calibration[:10]
    if phase == "calibration":
        return calibration
    return cases


def _run_one(
    *,
    prepared: PreparedCase,
    provider: OpenRouterStructuredModelProvider,
    config: RunConfig,
) -> dict[str, Any]:
    case = prepared.case
    started = time.perf_counter()
    try:
        generated = provider.generate_structured(
            prompt=build_legal_fact_prompt(prepared.text),
            json_schema=LEGAL_FACT_SCHEMA,
            max_output_tokens=config.max_output_tokens,
            thinking_level=config.reasoning,
        )
        predicted = validate_legal_fact_payload(generated.value)
        score = score_legal_fact_extraction(
            expected=prepared.expected,
            predicted=predicted,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        metadata = generated.provider_metadata or {}
        return {
            "sample_id": case.sample_id,
            "split": case.split,
            "object_key": case.object_key,
            "page_index": case.page_index,
            "source_pdf_sha256": case.source_pdf_sha256,
            "reference_sha256": case.reference_sha256,
            "status": "completed",
            "model": generated.model,
            "requested_model": config.model,
            "routed_provider": str(metadata.get("routed_provider") or ""),
            "reasoning": config.reasoning,
            "structured_mode": config.structured_mode,
            "latency_ms": latency_ms,
            "input_tokens": generated.usage.input_tokens,
            "output_tokens": generated.usage.output_tokens,
            "thinking_tokens": generated.usage.thinking_tokens,
            "total_tokens": generated.usage.total_tokens,
            "cost_usd": generated.cost_usd,
            "predicted": predicted,
            "score": score.to_json_dict(),
            "error": None,
        }
    except (ModelProviderError, ValueError, TypeError, KeyError) as exc:
        return {
            "sample_id": case.sample_id,
            "split": case.split,
            "object_key": case.object_key,
            "page_index": case.page_index,
            "source_pdf_sha256": case.source_pdf_sha256,
            "reference_sha256": case.reference_sha256,
            "status": "failed",
            "requested_model": config.model,
            "reasoning": config.reasoning,
            "structured_mode": config.structured_mode,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "cost_usd": None,
            "predicted": None,
            "score": None,
            "error": f"{type(exc).__name__}: {exc}"[:2000],
        }


def _sum_optional(records: Iterable[dict[str, Any]], key: str) -> int | None:
    values = [record.get(key) for record in records]
    ints = [
        int(value)
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    return sum(ints) if ints else None


def _cost(records: Iterable[dict[str, Any]]) -> float:
    return sum(
        float(value)
        for record in records
        if isinstance((value := record.get("cost_usd")), (int, float))
        and not isinstance(value, bool)
    )


def _aggregate(records: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    completed = [record for record in records if record["status"] == "completed"]
    expected = predicted = matched = false_positive = false_negative = 0
    exact_pages = 0
    fields: dict[str, dict[str, int]] = {
        field: {
            "expected": 0,
            "predicted": 0,
            "matched": 0,
            "false_positive": 0,
            "false_negative": 0,
        }
        for field in LEGAL_FACT_FIELDS
    }
    for record in completed:
        score = record["score"]
        expected += int(score["expected"])
        predicted += int(score["predicted"])
        matched += int(score["matched"])
        false_positive += int(score["false_positive"])
        false_negative += int(score["false_negative"])
        exact_pages += bool(score["exact_page"])
        for field in LEGAL_FACT_FIELDS:
            child = score["fields"][field]
            for key in fields[field]:
                fields[field][key] += int(child[key])
    precision = 1.0 if predicted == 0 and expected == 0 else (
        0.0 if predicted == 0 else matched / predicted
    )
    recall = 1.0 if expected == 0 else matched / expected
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    field_metrics: dict[str, dict[str, float | int]] = {}
    for field, counts in fields.items():
        p = 1.0 if counts["predicted"] == 0 and counts["expected"] == 0 else (
            0.0 if counts["predicted"] == 0 else counts["matched"] / counts["predicted"]
        )
        r = 1.0 if counts["expected"] == 0 else counts["matched"] / counts["expected"]
        field_metrics[field] = {
            **counts,
            "precision": p,
            "recall": r,
            "f1": 0.0 if p + r == 0 else 2 * p * r / (p + r),
        }
    latencies = [int(record["latency_ms"]) for record in completed]
    cost = _cost(records)
    return {
        "label": label,
        "requested_pages": len(records),
        "completed_pages": len(completed),
        "failed_pages": len(records) - len(completed),
        "structured_success_rate": len(completed) / len(records) if records else 0.0,
        "exact_pages": exact_pages,
        "exact_page_rate": exact_pages / len(completed) if completed else 0.0,
        "expected_facts": expected,
        "predicted_facts": predicted,
        "matched_facts": matched,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fields": field_metrics,
        "latency_ms_p50": statistics.median(latencies) if latencies else None,
        "latency_ms_p95": _percentile(latencies, 0.95),
        "input_tokens": _sum_optional(completed, "input_tokens"),
        "output_tokens": _sum_optional(completed, "output_tokens"),
        "thinking_tokens": _sum_optional(completed, "thinking_tokens"),
        "total_tokens": _sum_optional(completed, "total_tokens"),
        "cost_usd": cost,
        "cost_per_1000_pages_usd": (cost / len(completed) * 1000) if completed else None,
        "cost_per_exact_page_usd": (cost / exact_pages) if exact_pages else None,
    }


def _percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    overall = summary["metrics"]["overall"]
    lines = [
        "# Text legal-fact extraction benchmark",
        "",
        f"- model: `{summary['configuration']['model']}`",
        f"- reasoning: `{summary['configuration']['reasoning']}`",
        f"- phase: `{summary['configuration']['phase']}`",
        f"- completed: {overall['completed_pages']}/{overall['requested_pages']}",
        f"- precision: {overall['precision']:.4f}",
        f"- recall: {overall['recall']:.4f}",
        f"- F1: {overall['f1']:.4f}",
        f"- exact-page rate: {overall['exact_page_rate']:.4f}",
        f"- observed provider cost: ${overall['cost_usd']:.6f}",
        (
            f"- cost / 1,000 completed pages: "
            f"${overall['cost_per_1000_pages_usd']:.4f}"
            if overall["cost_per_1000_pages_usd"] is not None
            else "- cost / 1,000 completed pages: n/a"
        ),
    ]
    (path.parent / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    if args.max_concurrency < 1 or args.max_concurrency > 32:
        raise ValueError("--max-concurrency must be between 1 and 32")
    if args.max_cost_usd <= 0:
        raise ValueError("--max-cost-usd must be positive")
    prepared_cases, manifest = _load_cases(
        config_path=args.config,
        prepared_root=args.prepared_root,
    )
    selected = _phase_cases(prepared_cases, args.phase)
    settings = get_openrouter_settings()
    config = RunConfig(
        model=args.model,
        reasoning=args.reasoning,
        structured_mode=args.structured_mode,
        provider_order=tuple(
            part.strip() for part in args.provider_order.split(",") if part.strip()
        ),
        max_output_tokens=args.max_output_tokens,
    )
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required for live benchmark calls")
    provider = OpenRouterStructuredModelProvider(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        model=config.model,
        structured_mode=config.structured_mode,  # type: ignore[arg-type]
        provider_order=config.provider_order,
        allow_provider_fallbacks=not bool(config.provider_order),
        max_structured_attempts=2,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.max_concurrency) as executor:
        futures = {
            executor.submit(
                _run_one, prepared=prepared, provider=provider, config=config
            ): prepared.case.sample_id
            for prepared in selected
        }
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            print(
                json.dumps(
                    {
                        key: record.get(key)
                        for key in (
                            "sample_id",
                            "status",
                            "cost_usd",
                            "latency_ms",
                            "error",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    order = {
        prepared.case.sample_id: index for index, prepared in enumerate(selected)
    }
    records.sort(key=lambda record: order[str(record["sample_id"])])
    result_path = args.output / "results.jsonl"
    result_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    metrics: dict[str, Any] = {"overall": _aggregate(records, label="overall")}
    for split in ("calibration", "holdout"):
        subset = [record for record in records if record["split"] == split]
        if subset:
            metrics[split] = _aggregate(subset, label=split)
    total_cost = metrics["overall"]["cost_usd"]
    summary = {
        "schema_version": 1,
        "benchmark_kind": "scj_principales_text_legal_fact_extraction",
        "configuration": {
            "phase": args.phase,
            "model": config.model,
            "reasoning": config.reasoning,
            "structured_mode": config.structured_mode,
            "provider_order": list(config.provider_order),
            "max_output_tokens": config.max_output_tokens,
            "max_concurrency": args.max_concurrency,
            "max_cost_usd": args.max_cost_usd,
        },
        "corpus": {
            "records": manifest["source_visual_benchmark"]["expected_records"],
            "calibration_records": manifest["expected_calibration_records"],
            "holdout_records": manifest["expected_holdout_records"],
            "reference_authority": manifest["reference_authority"],
            "source_visual_benchmark": manifest["source_visual_benchmark"],
        },
        "metrics": metrics,
        "budget_status": "PASS" if total_cost <= args.max_cost_usd else "FAIL",
    }
    _write_summary(args.output / "summary.json", summary)
    if total_cost > args.max_cost_usd:
        print(
            f"observed cost ${total_cost:.6f} exceeded cap ${args.max_cost_usd:.6f}",
            flush=True,
        )
        return 2
    # Semantic quality is reported, not gated yet. This first live run is the baseline.
    return 0 if metrics["overall"]["completed_pages"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
