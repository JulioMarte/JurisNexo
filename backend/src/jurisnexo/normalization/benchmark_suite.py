from __future__ import annotations

from collections.abc import Iterable
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


def parse_configs(spec: str) -> tuple[str, ...]:
    requested = tuple(
        part.strip() for part in spec.split(",") if part.strip()
    )
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


def resume_key(config: str, source_sha256: str, page_index: int) -> str:
    return f"{config}|{source_sha256}|{page_index}"


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
    document_pass_rate = (
        sum(
            1
            for document_records in grouped.values()
            if all(
                record.critical_matched_count
                >= record.critical_expected_count
                for record in document_records
            )
        )
        / len(grouped)
    )
    return len(grouped), documents_with_critical_loss, document_pass_rate


def aggregate_records(
    records: Iterable[SuiteRecord],
) -> dict[str, Any]:
    by_config: dict[str, list[SuiteRecord]] = {}
    for record in records:
        by_config.setdefault(record.config, []).append(record)

    report: dict[str, Any] = {}
    for config, config_records in sorted(by_config.items()):
        page_count = len(config_records)
        elapsed = [record.elapsed_seconds for record in config_records]
        total_seconds = sum(elapsed)
        expected = sum(
            record.critical_expected_count for record in config_records
        )
        matched = sum(
            record.critical_matched_count for record in config_records
        )
        documents, documents_with_critical_loss, document_pass_rate = (
            document_aggregates(tuple(config_records))
        )
        output_bytes = sum(record.output_bytes for record in config_records)
        report[config] = {
            "page_count": page_count,
            "document_count": documents,
            "quality": {
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
                    record.token_content_precision
                    for record in config_records
                ),
                "mean_token_order_preservation": mean(
                    record.token_order_preservation
                    for record in config_records
                ),
                "aggregate_legal_critical_recall": (
                    1.0 if expected == 0 else matched / expected
                ),
                "documents_with_critical_loss": documents_with_critical_loss,
                "document_pass_rate": document_pass_rate,
            },
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
                "model_cost_usd": 0.0,
                "cost_per_page_usd": 0.0,
                "cost_per_document_usd": 0.0,
                "output_bytes_per_page": (
                    output_bytes / page_count if page_count else 0.0
                ),
            },
        }
    return report


def format_summary(report: dict[str, Any], *, recorded: int) -> str:
    lines = [
        "# SCJ Principales corpus suite",
        "",
        f"Recorded page evaluations: {recorded}",
        "",
        "| config | pages | docs | mean WER | p95 WER | recall | precision | "
        "order | legal-critical | doc pass | s/page | pages/s | $/page |",
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
            f"{quality['document_pass_rate']:.4f} | "
            f"{speed['mean_seconds_per_page']:.3f} | "
            f"{speed['pages_per_second']:.3f} | "
            f"{cost['cost_per_page_usd']:.6f} |"
        )
    lines.append("")
    lines.append(
        "Cost is provider/model cost. Technical normalization runs locally, so "
        "its provider cost is 0; interpret seconds/page as the current compute "
        "cost proxy. Legal-critical recall counts spans recognised by the "
        "current detector."
    )
    return "\n".join(lines) + "\n"
