from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import mean
from typing import Any, cast

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
    reference_reliable: bool = True
    reference_risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    max_mean_word_error_rate: float = 0.10
    min_mean_token_content_recall: float = 0.98
    min_mean_token_content_precision: float = 0.98
    min_aggregate_legal_critical_recall: float = 1.0
    min_sampled_document_pass_rate: float = 1.0
    max_unreliable_reference_pages: int = 0


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


def aggregate_records(
    records: Iterable[SuiteRecord],
    *,
    compute_hourly_usd: float | None = None,
) -> dict[str, Any]:
    if compute_hourly_usd is not None and compute_hourly_usd < 0:
        raise ValueError("compute_hourly_usd must be non-negative")
    by_config: dict[str, list[SuiteRecord]] = {}
    for record in records:
        by_config.setdefault(record.config, []).append(record)

    report: dict[str, Any] = {}
    for config, config_records in sorted(by_config.items()):
        page_count = len(config_records)
        all_document_count = len(
            {record.source_sha256 for record in config_records}
        )
        scored_records = [
            record for record in config_records if record.reference_reliable
        ]
        reference_unreliable_records = [
            record for record in config_records if not record.reference_reliable
        ]
        if not scored_records:
            raise ValueError(
                f"configuration {config!r} has no reliable reference pages to score"
            )
        elapsed = [record.elapsed_seconds for record in config_records]
        total_seconds = sum(elapsed)
        expected = sum(
            record.critical_expected_count for record in scored_records
        )
        matched = sum(
            record.critical_matched_count for record in scored_records
        )
        documents, documents_with_critical_loss, sampled_document_pass_rate = (
            document_aggregates(tuple(scored_records))
        )
        output_bytes = sum(record.output_bytes for record in config_records)
        modeled_compute_usd = (
            None
            if compute_hourly_usd is None
            else (total_seconds / 3600.0) * compute_hourly_usd
        )
        quality = {
            "mean_word_error_rate": mean(
                record.word_error_rate for record in scored_records
            ),
            "median_word_error_rate": percentile(
                [record.word_error_rate for record in scored_records], 0.5
            ),
            "p95_word_error_rate": percentile(
                [record.word_error_rate for record in scored_records], 0.95
            ),
            "mean_character_error_rate": mean(
                record.character_error_rate for record in scored_records
            ),
            "mean_token_content_recall": mean(
                record.token_content_recall for record in scored_records
            ),
            "mean_token_content_precision": mean(
                record.token_content_precision for record in scored_records
            ),
            "mean_token_order_preservation": mean(
                record.token_order_preservation for record in scored_records
            ),
            "aggregate_legal_critical_recall": (
                1.0 if expected == 0 else matched / expected
            ),
            "documents_with_critical_loss": documents_with_critical_loss,
            "sampled_document_pass_rate": sampled_document_pass_rate,
            "reference_scored_page_count": len(scored_records),
            "reference_unreliable_page_count": len(
                reference_unreliable_records
            ),
            "reference_unreliable_document_count": len(
                {record.source_sha256 for record in reference_unreliable_records}
            ),
        }
        quality.update(_document_quality(scored_records))
        report[config] = {
            "page_count": page_count,
            "document_count": all_document_count,
            "quality_reference_document_count": documents,
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
                "assumed_compute_hourly_usd": compute_hourly_usd,
                "modeled_normalization_compute_usd": modeled_compute_usd,
                "modeled_compute_cost_per_page_usd": (
                    None
                    if modeled_compute_usd is None or page_count == 0
                    else modeled_compute_usd / page_count
                ),
                "modeled_compute_cost_per_document_usd": (
                    None
                    if modeled_compute_usd is None or all_document_count == 0
                    else modeled_compute_usd / all_document_count
                ),
            },
        }
    return report


def _metric_float(metrics: Mapping[str, object], key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"quality metric {key!r} is not numeric")
    return float(value)


def evaluate_quality_gates(
    report: Mapping[str, object],
    *,
    required_configs: tuple[str, ...],
    thresholds: QualityThresholds,
) -> dict[str, Any]:
    configs: dict[str, Any] = {}
    for config in required_configs:
        metrics_raw = report.get(config)
        if not isinstance(metrics_raw, Mapping):
            configs[config] = {
                "passed": False,
                "checks": {"present": False},
            }
            continue
        metrics = cast(Mapping[str, object], metrics_raw)
        quality_raw = metrics.get("quality")
        if not isinstance(quality_raw, Mapping):
            configs[config] = {
                "passed": False,
                "checks": {"present": False},
            }
            continue
        quality = cast(Mapping[str, object], quality_raw)
        checks = {
            "present": True,
            "mean_word_error_rate": (
                _metric_float(quality, "mean_word_error_rate")
                <= thresholds.max_mean_word_error_rate
            ),
            "mean_token_content_recall": (
                _metric_float(quality, "mean_token_content_recall")
                >= thresholds.min_mean_token_content_recall
            ),
            "mean_token_content_precision": (
                _metric_float(quality, "mean_token_content_precision")
                >= thresholds.min_mean_token_content_precision
            ),
            "aggregate_legal_critical_recall": (
                _metric_float(quality, "aggregate_legal_critical_recall")
                >= thresholds.min_aggregate_legal_critical_recall
            ),
            "sampled_document_pass_rate": (
                _metric_float(quality, "sampled_document_pass_rate")
                >= thresholds.min_sampled_document_pass_rate
            ),
            "reference_authority_complete": (
                _metric_float(quality, "reference_unreliable_page_count")
                <= thresholds.max_unreliable_reference_pages
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
            "max_unreliable_reference_pages": (
                thresholds.max_unreliable_reference_pages
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
        "| config | pages | ref scored | ref blocked | docs | mean WER | p95 WER | "
        "recall | precision | order | legal-critical | sampled doc pass | s/page | "
        "pages/s | provider $/page |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- |",
    ]
    for config, metrics in report.items():
        quality = metrics["quality"]
        speed = metrics["speed"]
        cost = metrics["cost"]
        lines.append(
            f"| {config} | {metrics['page_count']} | "
            f"{quality['reference_scored_page_count']} | "
            f"{quality['reference_unreliable_page_count']} | "
            f"{metrics['document_count']} | "
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
        "actually evaluated; it is not a full-document production verdict. Pages "
        "whose extracted reference is flagged as unreliable are processed and "
        "accounted for but excluded from fidelity means; required routes still fail "
        "the reference-authority gate until those pages receive trusted gold."
    )
    return "\n".join(lines) + "\n"
