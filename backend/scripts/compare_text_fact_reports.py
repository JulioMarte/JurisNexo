from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    reports: list[dict[str, Any]] = []
    for path in sorted(Path(args.input).rglob("report.json")):
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    if not reports:
        raise RuntimeError("no text fact reports found")
    rows = []
    for report in reports:
        summary = report["summary"]
        rows.append({
            "model": report["model"],
            "reasoning": report.get("reasoning"),
            "completed": summary["completed_pages"],
            "failed": summary["failed_pages"],
            "precision": summary["precision"],
            "recall": summary["recall"],
            "f1": summary["f1"],
            "missed": summary["missed_facts"],
            "hallucinated": summary["hallucinated_facts"],
            "pages_with_miss": summary["pages_with_any_miss"],
            "pages_with_hallucination": summary["pages_with_any_hallucination"],
            "p50_ms": summary["latency_p50_ms"],
            "p95_ms": summary["latency_p95_ms"],
            "cost_total_usd": summary["cost_total_usd"],
            "cost_per_1000_pages_usd": summary["cost_per_1000_pages_usd"],
            "tokens": summary["tokens"],
        })
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps({"schema_version": 1, "models": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "## Aligned-text legal fact comparison",
        "",
        "| Model | Reasoning | Done | F1 | Recall | Precision | Missed | Hallucinated | p50 ms | Cost/1k pages |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['model']} | {row['reasoning']} | {row['completed']} | {row['f1']:.4f} | {row['recall']:.4f} | {row['precision']:.4f} | {row['missed']} | {row['hallucinated']} | {row['p50_ms']} | ${(row['cost_per_1000_pages_usd'] or 0):.4f} |"
        )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
