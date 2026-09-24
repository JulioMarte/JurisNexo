from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import mean
from typing import Any

ROUTES = ("pdf_aware", "full_ocr")


@dataclass(frozen=True, slots=True)
class SuiteRecord:
    config: str
    source_sha256: str
    object_key: str
    page_index: int
    document_page_count: int
    elapsed_seconds: float
    output_bytes: int
    character_error_rate: float
    word_error_rate: float
    token_content_recall: float
    token_content_precision: float
    token_order_preservation: float
    legal_critical_recall: float
    critical_expected_count: int
    critical_matched_count: int
    benchmark_identity: str = "legacy-unversioned"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    max_mean_word_error_rate: float = 0.10
    min_mean_token_content_recall: float = 0.98
    min_mean_token_content_precision: float = 0.98
    min_aggregate_legal_critical_recall: float = 1.0
    min_sampled_document_pass_rate: float = 1.0


def parse_configs(spec: str) -> tuple[str, ...]:
    requested = tuple(part.strip() for part in spec.split(",") if part.strip())
    if not requested:
        raise ValueError("at least one configuration route is required")
    unknown = [item for item in requested if item not in ROUTES]
    if unknown:
        raise ValueError(f"unknown suite configurations: {unknown}")
    seen: list[str] = []
    for item in requested:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def validate_shard(*, shard_index: int, shard_count: int) -> None:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must satisfy 0 <= index < shard_count")


def shard_for_sha(source_sha256: str, *, shard_count: int) -> int:
    validate_shard(shard_index=0, shard_count=shard_count)
    if len(source_sha256) < 16:
        raise ValueError("source_sha256 must contain at least 16 hexadecimal characters")
    try:
        prefix = int(source_sha256[:16], 16)
    except ValueError as exc:
        raise ValueError("source_sha256 must be hexadecimal") from exc
    return prefix % shard_count


def resume_key(
    config: str,
    source_sha256: str,
    page_index: int,
    benchmark_identity: str = "legacy-unversioned",
) -> str:
    return f"{config}|{source_sha256}|{page_index}|{benchmark_identity}"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def document_aggregates(
    records: tuple[SuiteRecord, ...],
) -> tuple[int, int, float]:
    grouped: dict[str, list[SuiteRecord]] = {}
    for record in records:
        grouped.setdefault(record.source_sha256, []).append(record)
    documents_with_critical_loss = sum(
        1
        for document_records in grouped.values()
        if any(
            record.critical_matched_count < record.critical_expected_count
            for record in document_records
        )
    )
    if not grouped:
        return 0, 0, 1.0
    sampled_document_pass_rate = (
        sum(
            1
            for document_records in grouped.values()
            if all(
                record.critical_matched_count >= record.critical_expected_count
                for record in document_records
            )
        )
        / len(grouped)
    )
    return len(grouped), documents_with_critical_loss, sampled_document_pass_rate


def _document_quality(config_records: list[SuiteRecord]) -> dict[str, float]:
    grouped: dict[str, list[SuiteRecord]] = {}
    for record in config_records:
        grouped.setdefault(record.source_sha256, []).append(record)
    if not grouped:
        return {
            "mean_document_word_error_rate": 0.0,
            "median_document_word_error_rate": 0.0,
            "p95_document_worst_page_word_error_rate": 0.0,
        }
    document_means = [
        mean(record.word_error_rate for record in document_records)
        for document_records in grouped.values()
    ]
    document_worst = [
        max(record.word_error_rate for record in document_records)
        for document_records in grouped.values()
    ]
    return {
        "mean_document_word_error_rate": mean(document_means),
        "median_document_word_error_rate": percentile(document_means, 0.5),
        "p95_document_worst_page_word_error_rate": percentile(document_worst, 0.95),
    }


def aggregate_records(\n    records: Iterable[SuiteRecord],\n    *,\n    compute_hourly_usd: float | None = None,\n) -> dict[str, Any]:\n    if compute_hourly_usd is not None and compute_hourly_usd < 0:\n        raise ValueError("compute_hourly_usd must be non-negative")
    by_config: dict[str, list[SuiteRecord]] = {}
    for record in records:
        by_config.setdefault(record.config, []).append(record)

    report: dict[str, Any] = {}
    for config, config_records in sorted(by_config.items()):
        page_count = len(config_records)
        elapsed = [record.elapsed_seconds for record in config_records]
        total_seconds = sum(elapsed)
        expected = sum(record.critical_expected_count for record in config_records)
        matched = sum(record.critical_matched_count for record in config_records)
        documents, documents_with_critical_loss, sampled_document_pass_rate = (
            document_aggregates(tuple(config_records))
        )
        output_bytes = sum(record.output_bytes for record in config_records)
        quality = {
            "mean_word_error_rate": mean(
                record.word_error_rate for record in config_records
            ),
            "median_word_error_rate": percentile(
                [record.word_error_rate for record in config_records], 0.5
            ),
            "p95_word_error_rate": percentile(
                [record.word_error_rate for record in config_records], 0.95
            ),
            "mean_character_error_rate": mean(
                record.character_error_rate for record in config_records
            ),
            "mean_token_content_recall": mean(
                record.token_content_recall for record in config_records
            ),
            "mean_token_content_precision": mean(
                record.token_content_precision for record in config_records
            ),
            "mean_token_order_preservation": mean(
                record.token_order_preservation for record in config_records
            ),
            "aggregate_legal_critical_recall": (
                1.0 if expected == 0 else matched / expected
            ),
            "documents_with_critical_loss": documents_with_critical_loss,
            "sampled_document_pass_rate": sampled_document_pass_rate,
        }
        quality.update(_document_quality(config_records))
        report[config] = {
            "page_count": page_count,
            "document_count": documents,
            "quality": quality,
            "speed": {
                "total_seconds": total_seconds,
                "mean_seconds_per_page": (
                    total_seconds / page_count if page_count else 0.0
                ),
                "median_seconds_per_page": percentile(elapsed, 0.5),
                "p95_seconds_per_page": percentile(elapsed, 0.95),
                "pages_per_second": (
                    page_count / total_seconds if total_seconds else 0.0
                ),
            },
            "cost": {
                "provider_model_cost_usd": 0.0,
                "provider_cost_per_page_usd": 0.0,
                "provider_cost_per_document_usd": 0.0,
                "output_bytes_per_page": (
                    output_bytes / page_count if page_count else 0.0
                ),
            },
        }
    return report


def evaluate_quality_gates(
    report: Mapping[str, Any],
    *,
    required_configs: tuple[str, ...],
    thresholds: QualityThresholds,
) -> dict[str, Any]:
    configs: dict[str, Any] = {}
    for config in required_configs:
        metrics = report.get(config)
        if not isinstance(metrics, dict):
            configs[config] = {
                "passed": False,
                "checks": {"present": False},
            }
            continue
        quality = metrics["quality"]
        checks = {
            "present": True,
            "mean_word_error_rate": (
                float(quality["mean_word_error_rate"])
                <= thresholds.max_mean_word_error_rate
            ),
            "mean_token_content_recall": (
                float(quality["mean_token_content_recall"])
                >= thresholds.min_mean_token_content_recall
            ),
            "mean_token_content_precision": (
                float(quality["mean_token_content_precision"])
                >= thresholds.min_mean_token_content_precision
            ),
            "aggregate_legal_critical_recall": (
                float(quality["aggregate_legal_critical_recall"])
                >= thresholds.min_aggregate_legal_critical_recall
            ),
            "sampled_document_pass_rate": (
                float(quality["sampled_document_pass_rate"])
                >= thresholds.min_sampled_document_pass_rate
            ),
        }
        configs[config] = {
            "passed": all(checks.values()),
            "checks": checks,
        }
    return {
        "passed": all(item["passed"] for item in configs.values()),
        "required_configs": list(required_configs),
        "thresholds": {
            "max_mean_word_error_rate": thresholds.max_mean_word_error_rate,
            "min_mean_token_content_recall": thresholds.min_mean_token_content_recall,
            "min_mean_token_content_precision": thresholds.min_mean_token_content_precision,
            "min_aggregate_legal_critical_recall": (
                thresholds.min_aggregate_legal_critical_recall
            ),
            "min_sampled_document_pass_rate": (
                thresholds.min_sampled_document_pass_rate
            ),
        },
        "configs": configs,
    }


def format_summary(
    report: dict[str, Any],
    *,
    recorded: int,
    quality_gate: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# SCJ Principales corpus suite",
        "",
        f"Recorded current-identity page evaluations: {recorded}",
        "",
        "| config | pages | docs | mean WER | p95 WER | recall | precision | "
        "order | legal-critical | sampled doc pass | s/page | pages/s | provider $/page |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- |",
    ]
    for config, metrics in report.items():
        quality = metrics["quality"]
        speed = metrics["speed"]
        cost = metrics["cost"]
        lines.append(
            f"| {config} | {metrics['page_count']} | {metrics['document_count']} | "
            f"{quality['mean_word_error_rate']:.4f} | "
            f"{quality['p95_word_error_rate']:.4f} | "
            f"{quality['mean_token_content_recall']:.4f} | "
            f"{quality['mean_token_content_precision']:.4f} | "
            f"{quality['mean_token_order_preservation']:.4f} | "
            f"{quality['aggregate_legal_critical_recall']:.4f} | "
            f"{quality['sampled_document_pass_rate']:.4f} | "
            f"{speed['mean_seconds_per_page']:.3f} | "
            f"{speed['pages_per_second']:.3f} | "
            f"{cost['provider_cost_per_page_usd']:.6f} |"
        )
    if quality_gate is not None:
        lines.extend(
            [
                "",
                "## Quality gate",
                "",
                "**PASS**" if bool(quality_gate.get("passed")) else "**FAIL**",
                "",
                "Workflow execution and quality acceptance are separate: a report can "
                "be produced successfully while a required route fails its quality gate.",
            ]
        )
    lines.append("")
    lines.append(
        "Provider/model cost excludes local compute. Technical normalization runs "
        "locally, so provider cost is 0; seconds/page and bytes/page are the "
        "current operational-cost proxies. Legal-critical recall counts spans "
        "recognised by the current detector. 'Sampled doc pass' only covers pages "
        "actually evaluated; it is not a full-document production verdict."
    )
    return "\n".join(lines) + "\n"
