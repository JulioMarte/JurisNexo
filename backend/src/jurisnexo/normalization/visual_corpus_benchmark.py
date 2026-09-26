from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from jurisnexo.normalization.benchmark_suite import percentile


@dataclass(frozen=True, slots=True)
class VisualCorpusRecord:
    sample_id: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    character_error_rate: float
    word_error_rate: float
    token_content_recall: float
    token_content_precision: float
    token_content_f1: float
    token_order_preservation: float
    legal_critical_recall: float
    critical_expected_count: int
    critical_matched_count: int
    reference_reliable: bool
    model_confidence: float | None
    unreadable: bool
    routed_provider: str
    error: str | None = None


def aggregate_visual_records(records: list[VisualCorpusRecord], *, expected_pages: int) -> dict[str, Any]:
    if expected_pages < 1:
        raise ValueError("expected_pages must be positive")
    completed = [record for record in records if record.error is None]
    reliable = [record for record in completed if record.reference_reliable]
    latencies = [float(record.latency_ms) for record in completed]
    costs = [record.cost_usd for record in completed if record.cost_usd is not None]
    expected_critical = sum(record.critical_expected_count for record in reliable)
    matched_critical = sum(record.critical_matched_count for record in reliable)
    pages_with_potential_error = sum(
        record.word_error_rate > 0.0 or record.legal_critical_recall < 1.0
        for record in reliable
    )
    pages_with_critical_loss = sum(record.legal_critical_recall < 1.0 for record in reliable)
    total_cost = sum(costs)
    return {
        "expected_pages": expected_pages,
        "completed_pages": len(completed),
        "failed_pages": len(records) - len(completed),
        "coverage": len(completed) / expected_pages,
        "reference_scored_pages": len(reliable),
        "reference_blocked_pages": len(completed) - len(reliable),
        "quality": {
            "mean_character_error_rate": mean(record.character_error_rate for record in reliable) if reliable else None,
            "mean_word_error_rate": mean(record.word_error_rate for record in reliable) if reliable else None,
            "median_word_error_rate": percentile([record.word_error_rate for record in reliable], 0.5) if reliable else None,
            "p95_word_error_rate": percentile([record.word_error_rate for record in reliable], 0.95) if reliable else None,
            "mean_token_content_recall": mean(record.token_content_recall for record in reliable) if reliable else None,
            "mean_token_content_precision": mean(record.token_content_precision for record in reliable) if reliable else None,
            "mean_token_content_f1": mean(record.token_content_f1 for record in reliable) if reliable else None,
            "mean_token_order_preservation": mean(record.token_order_preservation for record in reliable) if reliable else None,
            "aggregate_legal_critical_recall": 1.0 if expected_critical == 0 else matched_critical / expected_critical,
            "pages_with_potential_error": pages_with_potential_error,
            "potential_error_page_rate": pages_with_potential_error / len(reliable) if reliable else None,
            "pages_with_critical_loss": pages_with_critical_loss,
            "critical_loss_page_rate": pages_with_critical_loss / len(reliable) if reliable else None,
            "unreadable_page_rate": sum(record.unreadable for record in completed) / len(completed) if completed else None,
        },
        "latency": {
            "mean_ms": mean(latencies) if latencies else None,
            "p50_ms": percentile(latencies, 0.5) if latencies else None,
            "p95_ms": percentile(latencies, 0.95) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
        },
        "tokens": {
            "input_total": sum(record.input_tokens or 0 for record in completed),
            "output_total": sum(record.output_tokens or 0 for record in completed),
            "thinking_total": sum(record.thinking_tokens or 0 for record in completed),
        },
        "cost": {
            "total_usd": total_cost,
            "mean_per_completed_page_usd": total_cost / len(completed) if completed else None,
            "projected_per_1000_pages_usd": (total_cost / len(completed) * 1000) if completed else None,
        },
    }
