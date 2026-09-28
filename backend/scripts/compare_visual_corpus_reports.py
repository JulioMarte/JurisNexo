from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_reports(root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(root.rglob("report.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            reports.append(data)
    if not reports:
        raise RuntimeError(f"no report.json files found under {root}")
    return reports


def _page_rows(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_sample: dict[str, dict[str, Any]] = {}
    for report in reports:
        model = str(report.get("model") or "<unknown>")
        records = report.get("records")
        if not isinstance(records, list):
            continue
        for raw in records:
            if not isinstance(raw, dict):
                continue
            sample_id = str(raw.get("sample_id") or "")
            if not sample_id:
                continue
            row = rows_by_sample.setdefault(
                sample_id,
                {
                    "sample_id": sample_id,
                    "object_key": raw.get("object_key"),
                    "page_index": raw.get("page_index"),
                    "models": {},
                },
            )
            models = row["models"]
            if not isinstance(models, dict):
                raise TypeError("models bucket is not a mapping")
            tokens = raw.get("tokens")
            token_data = tokens if isinstance(tokens, dict) else {}
            models[model] = {
                "status": "error" if raw.get("error") else "ok",
                "error": raw.get("error"),
                "latency_ms": raw.get("api_latency_ms"),
                "cost_usd": raw.get("cost_usd"),
                "input_tokens": token_data.get("input_tokens"),
                "completion_tokens": token_data.get("completion_tokens"),
                "reasoning_tokens": token_data.get("reasoning_tokens"),
                "answer_tokens_estimated": token_data.get(
                    "answer_tokens_estimated"
                ),
                "total_tokens": token_data.get("total_tokens"),
                "word_error_rate": raw.get("word_error_rate"),
                "character_error_rate": raw.get(
                    "character_error_rate"
                ),
                "token_content_f1": raw.get("token_content_f1"),
                "token_order_preservation": raw.get(
                    "token_order_preservation"
                ),
                "legal_critical_recall": raw.get(
                    "legal_critical_recall"
                ),
            }
    return [rows_by_sample[key] for key in sorted(rows_by_sample)]


def _markdown(
    pages: list[dict[str, Any]],
    model_order: list[str],
) -> str:
    lines = [
        "# Visual corpus comparison",
        "",
        (
            "Completion tokens can include reasoning tokens. "
            "Answer-estimated = completion - reasoning when reported."
        ),
        "",
    ]
    for page in pages:
        lines.extend(
            [
                f"## {page['sample_id']}",
                "",
                (
                    f"Source: {page.get('object_key')} "
                    f"page index {page.get('page_index')}"
                ),
                "",
                (
                    "| Model | Status | Input | Completion | Reasoning | "
                    "Answer est. | Total | Cost USD | Latency ms | WER | F1 |"
                ),
                (
                    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
                ),
            ]
        )
        models = page["models"]
        if not isinstance(models, dict):
            continue
        for model in model_order:
            data = models.get(model)
            if not isinstance(data, dict):
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        model,
                        str(data.get("status")),
                        str(data.get("input_tokens")),
                        str(data.get("completion_tokens")),
                        str(data.get("reasoning_tokens")),
                        str(data.get("answer_tokens_estimated")),
                        str(data.get("total_tokens")),
                        str(data.get("cost_usd")),
                        str(data.get("latency_ms")),
                        str(data.get("word_error_rate")),
                        str(data.get("token_content_f1")),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reports = _load_reports(args.input)
    model_order = [
        str(report.get("model") or "<unknown>")
        for report in reports
    ]
    pages = _page_rows(reports)
    payload = {
        "schema_version": 1,
        "model_count": len(model_order),
        "models": model_order,
        "page_count": len(pages),
        "pages": pages,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output / "summary.md").write_text(
        _markdown(pages, model_order),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
