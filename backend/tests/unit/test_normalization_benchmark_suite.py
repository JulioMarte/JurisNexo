from __future__ import annotations

import pytest

from jurisnexo.normalization.benchmark_suite import (
    QualityThresholds,
    SuiteRecord,
    aggregate_records,
    document_aggregates,
    evaluate_quality_gates,
    format_summary,
    parse_configs,
    percentile,
    resume_key,
)


def _record(
    *,
    config: str,
    sha: str,
    page: int,
    wer: float,
    expected: int = 2,
    matched: int = 2,
    seconds: float = 1.0,
    output_bytes: int = 1000,
) -> SuiteRecord:
    return SuiteRecord(
        config=config,
        source_sha256=sha,
        object_key=f"jurisdictions/do/scj/principales-sentencias/{sha[:2]}/{sha}.pdf",
        page_index=page,
        document_page_count=500,
        elapsed_seconds=seconds,
        output_bytes=output_bytes,
        character_error_rate=wer,
        word_error_rate=wer,
        token_content_recall=1.0 - wer,
        token_content_precision=1.0,
        token_order_preservation=1.0 - wer,
        legal_critical_recall=1.0 if matched == expected else matched / expected,
        critical_expected_count=expected,
        critical_matched_count=matched,
    )


def test_parse_configs_deduplicates_and_validates() -> None:
    assert parse_configs("pdf_aware, full_ocr,pdf_aware") == (
        "pdf_aware",
        "full_ocr",
    )
    with pytest.raises(ValueError):
        parse_configs("")
    with pytest.raises(ValueError):
        parse_configs("marker")


def test_resume_key_is_stable_and_versioned() -> None:
    assert resume_key("pdf_aware", "abc", 3, "v1") == "pdf_aware|abc|3|v1"
    assert resume_key("pdf_aware", "abc", 3, "v1") != resume_key(
        "pdf_aware", "abc", 3, "v2"
    )


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert percentile([], 0.95) == 0.0


def test_document_aggregates_detects_critical_loss() -> None:
    records = (
        _record(config="pdf_aware", sha="a" * 64, page=1, wer=0.01),
        _record(config="pdf_aware", sha="a" * 64, page=2, wer=0.02),
        _record(
            config="pdf_aware",
            sha="b" * 64,
            page=1,
            wer=0.05,
            expected=3,
            matched=2,
        ),
    )
    documents, with_loss, pass_rate = document_aggregates(records)
    assert documents == 2
    assert with_loss == 1
    assert pass_rate == pytest.approx(0.5)


def test_aggregate_records_reports_quality_speed_and_cost() -> None:
    records = (
        _record(config="pdf_aware", sha="a" * 64, page=1, wer=0.02, seconds=2.0),
        _record(config="pdf_aware", sha="a" * 64, page=2, wer=0.04, seconds=4.0),
        _record(config="full_ocr", sha="a" * 64, page=1, wer=0.30, seconds=6.0),
    )

    report = aggregate_records(records)

    assert set(report) == {"pdf_aware", "full_ocr"}
    pdf = report["pdf_aware"]
    assert pdf["page_count"] == 2
    assert pdf["document_count"] == 1
    assert pdf["quality"]["mean_word_error_rate"] == pytest.approx(0.03)
    assert pdf["speed"]["total_seconds"] == pytest.approx(6.0)
    assert pdf["speed"]["mean_seconds_per_page"] == pytest.approx(3.0)
    assert pdf["cost"]["provider_model_cost_usd"] == 0.0
    assert pdf["cost"]["provider_cost_per_page_usd"] == 0.0
    assert pdf["cost"]["output_bytes_per_page"] == pytest.approx(1000.0)
    assert report["full_ocr"]["quality"]["mean_word_error_rate"] == pytest.approx(
        0.30
    )


def test_format_summary_includes_configuration_row() -> None:
    report = aggregate_records(
        (_record(config="pdf_aware", sha="a" * 64, page=1, wer=0.01),)
    )
    summary = format_summary(report, recorded=1)
    assert "pdf_aware" in summary
    assert "mean WER" in summary
    assert "Recorded current-identity page evaluations: 1" in summary


def test_quality_gate_is_independent_from_report_generation() -> None:
    report = aggregate_records(
        (
            _record(config="pdf_aware", sha="a" * 64, page=1, wer=0.01),
            _record(config="pdf_aware", sha="a" * 64, page=2, wer=0.01),
        )
    )
    gate = evaluate_quality_gates(
        report,
        required_configs=("pdf_aware",),
        thresholds=QualityThresholds(),
    )
    assert gate["passed"] is True
    assert gate["configs"]["pdf_aware"]["checks"]["present"] is True


def test_quality_gate_fails_on_critical_document_loss() -> None:
    report = aggregate_records(
        (
            _record(
                config="pdf_aware",
                sha="a" * 64,
                page=1,
                wer=0.02,
                expected=2,
                matched=1,
            ),
        )
    )
    gate = evaluate_quality_gates(
        report,
        required_configs=("pdf_aware",),
        thresholds=QualityThresholds(),
    )
    assert gate["passed"] is False
    assert gate["configs"]["pdf_aware"]["checks"]["document_pass_rate"] is False


def test_summary_labels_provider_cost_and_quality_verdict() -> None:
    report = aggregate_records(
        (_record(config="pdf_aware", sha="a" * 64, page=1, wer=0.01),)
    )
    gate = evaluate_quality_gates(
        report,
        required_configs=("pdf_aware",),
        thresholds=QualityThresholds(),
    )
    summary = format_summary(report, recorded=1, quality_gate=gate)
    assert "provider $/page" in summary
    assert "## Quality gate" in summary
    assert "**PASS**" in summary
