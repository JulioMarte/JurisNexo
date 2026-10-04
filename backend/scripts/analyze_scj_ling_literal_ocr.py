"""Deterministic offline analysis of the SCJ Principales Ling literal OCR evidence.

Reads the persisted Pass 1 / Pass 2 records for a frozen plan through the object
store (local mirror via ``JURISNEXO_LOCAL_OBJECT_ROOT``/``--object-root`` or the
configured S3-compatible store) and writes a machine-readable JSON report plus a
human Markdown report. It performs no model calls and is deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.local_object_store import LocalObjectStore
from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.ling_literal_ocr_analysis import (
    PageEvidence,
    analyze_evidence,
    pass_evidence_from_mapping,
)

DEFAULT_PLAN_SHA = "63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4"
DEFAULT_MODEL = "inclusionai/ling-3.0-flash-vl"
DEFAULT_PROVIDER = "NovitaAI"
OUTPUT_PREFIX = "benchmarks/scj-principales/ling-literal-ocr/v1"
LOCAL_OBJECT_ROOT_ENV = "JURISNEXO_LOCAL_OBJECT_ROOT"
LOCAL_CORPUS_ROOT_ENV = "JURISNEXO_LOCAL_CORPUS_ROOT"
PASS_KEY_PATTERN = re.compile(r"^pass-(\d+)\.json$")


def _local_object_root() -> Path | None:
    for env_name in (LOCAL_OBJECT_ROOT_ENV, LOCAL_CORPUS_ROOT_ENV):
        value = os.environ.get(env_name, "").strip()
        if value:
            return Path(value)
    return None


def _build_store(object_root: Path | None) -> Any:
    root = object_root or _local_object_root()
    if root is not None:
        return LocalObjectStore(root)
    return build_s3_object_store()


def _pages_prefix(plan_sha: str, model: str, provider: str) -> str:
    return f"{OUTPUT_PREFIX}/{plan_sha}/{model.replace('/', '__')}/{provider}/pages/"


def load_pages(
    store: Any,
    *,
    plan_sha: str,
    model: str,
    provider: str,
) -> list[PageEvidence]:
    prefix = _pages_prefix(plan_sha, model, provider)
    grouped: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for stored in store.list_objects(prefix):
        if not stored.key.endswith(".json"):
            continue
        relative = stored.key[len(prefix) :]
        parts = relative.split("/")
        if len(parts) != 3:
            continue
        match = PASS_KEY_PATTERN.match(parts[2])
        if match is None:
            continue
        payload = json.loads(store.get_bytes(stored.key))
        grouped.setdefault((parts[0], int(parts[1])), {})[int(match.group(1))] = payload

    pages: list[PageEvidence] = []
    for (document_id, page_index), passes in sorted(grouped.items()):
        if 1 not in passes:
            continue
        first = pass_evidence_from_mapping(passes[1])
        second = (
            pass_evidence_from_mapping(passes[2]) if 2 in passes else None
        )
        pages.append(
            PageEvidence(
                document_id=document_id,
                page_index=page_index,
                source_classification=str(passes[1].get("source_classification") or ""),
                first=first,
                second=second,
            )
        )
    return pages


def render_markdown(
    report: dict[str, Any],
    *,
    plan_sha: str,
    model: str,
    provider: str,
    object_root: str | None,
    code_revision: str,
) -> str:
    lines: list[str] = []
    lines.append("# SCJ Principales Ling literal OCR — deterministic evidence analysis")
    lines.append("")
    lines.append("Status: ROUTING EVIDENCE — divergence, output-quality and legal-span")
    lines.append("signals only. This is not a semantic-correctness claim about the")
    lines.append("transcriptions and does not overwrite the primary PDF source. The")
    lines.append("legal-span disagreements are the priority review set for independent")
    lines.append("(blind visual) adjudication; model output is never ground truth.")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Frozen plan SHA-256: `{plan_sha}`")
    lines.append(f"- Model / provider: `{model}` / `{provider}`")
    lines.append(f"- Code revision: `{code_revision}`")
    if object_root:
        lines.append(f"- Object store: local mirror at `{object_root}`")
    else:
        lines.append("- Object store: configured S3-compatible durable store")
    lines.append("- Analyzer: `backend/scripts/analyze_scj_ling_literal_ocr.py`")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Pages with Pass 1: **{report['page_count']}**")
    lines.append(f"- Pages missing Pass 2: **{report['missing_second_pass']}**")
    lines.append(f"- Source classifications: `{report['source_classifications']}`")
    lines.append("")
    lines.append("## Pass 1 vs Pass 2 change taxonomy")
    lines.append("")
    lines.append("| Class | Pages |")
    lines.append("| --- | ---: |")
    for name, count in report["change_taxonomy"].items():
        lines.append(f"| {name} | {count} |")
    lines.append("")
    substantive = report["substantive"]
    sim = substantive["similarity"]
    lines.append("## Substantive divergence")
    lines.append("")
    lines.append(f"- Substantive pages: **{substantive['count']}**")
    if substantive["count"]:
        lines.append(
            "- Similarity min / p25 / median / p75 / max: "
            f"{sim['min']:.3f} / {sim['p25']:.3f} / {sim['median']:.3f} / "
            f"{sim['p75']:.3f} / {sim['max']:.3f}"
        )
    lines.append("")
    lines.append("Largest rewrites (lowest similarity first):")
    lines.append("")
    lines.append("| Page | Similarity | Length delta |")
    lines.append("| --- | ---: | ---: |")
    for row in substantive["largest_rewrites"]:
        lines.append(
            f"| {row['document_id']}/{row['page_index']} | {row['similarity']:.3f} "
            f"| {row['length_delta']} |"
        )
    lines.append("")
    lines.append("## Output-quality anomalies (routing only)")
    lines.append("")
    lines.append("| Anomaly | Pass 1 | Pass 2 |")
    lines.append("| --- | ---: | ---: |")
    for name in report["anomalies"]["pass1"]:
        lines.append(
            f"| {name} | {report['anomalies']['pass1'][name]} "
            f"| {report['anomalies']['pass2'][name]} |"
        )
    lines.append("")
    if report["anomaly_examples"]:
        lines.append("Example pages:")
        lines.append("")
        for label, examples in report["anomaly_examples"].items():
            lines.append(f"- `{label}`: {', '.join(examples)}")
        lines.append("")
    lines.append("## Legal-critical span disagreements")
    lines.append("")
    lines.append(
        f"{len(report['legal_disagreements'])} span-level disagreements across "
        "Pass 1 / Pass 2 — the priority review set."
    )
    lines.append("")
    lines.append("| Page | Category | Pass 1 only | Pass 2 only |")
    lines.append("| --- | --- | --- | --- |")
    for row in report["legal_disagreements"]:
        lines.append(
            f"| {row['document_id']}/{row['page_index']} | {row['category']} "
            f"| {', '.join(row['first_only']) or '—'} "
            f"| {', '.join(row['second_only']) or '—'} |"
        )
    lines.append("")
    runtime = report["runtime"]
    lines.append("## Runtime and provenance")
    lines.append("")
    lines.append(f"- Returned model mismatches: {runtime['returned_model_mismatch']}")
    lines.append(f"- Returned provider mismatches: {runtime['returned_provider_mismatch']}")
    lines.append(f"- Truncation suspects: {runtime['truncation_suspects']}")
    lines.append(f"- Render pixel-verified pairs: {runtime['render_pixel_verified']}")
    lines.append(f"- Render legacy-unverified pairs: {runtime['render_legacy_unverified']}")
    lines.append(f"- Completion tokens total: {runtime['completion_tokens_total']}")
    lines.append(f"- Cost total USD: {runtime['cost_total_usd']:.10f}")
    lines.append(f"- Cost pass 1 / pass 2 USD: {runtime['cost_pass1_usd']:.10f} / {runtime['cost_pass2_usd']:.10f}")
    lines.append("")
    lines.append("## Per-document detail")
    lines.append("")
    lines.append("| Document | Pages | Changed | Substantive | Legal | Anomalies | Cost USD |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for doc in report["documents"]:
        lines.append(
            f"| {doc['document_id']} | {doc['pages']} | {doc['changed']} "
            f"| {doc['substantive']} | {doc['legal_disagreements']} "
            f"| {doc['anomalies']} | {doc['cost_usd']:.6f} |"
        )
    lines.append("")
    lines.append("## Reproduction")
    lines.append("")
    lines.append("```text")
    lines.append("python backend/scripts/analyze_scj_ling_literal_ocr.py \\")
    lines.append(f"  --plan-sha {plan_sha} \\")
    lines.append("  --output <dir> [--object-root <local-mirror>]")
    lines.append("```")
    lines.append("")
    lines.append(
        "Without `--object-root` the analyzer reads the configured S3-compatible "
        "durable store; with it, a local directory mirroring object-store keys. "
        "Results are deterministic for the frozen plan. A new model, provider or "
        "plan is a new evidence generation."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-root", "--corpus-root", dest="object_root", type=Path, default=None)
    parser.add_argument("--plan-sha", default=DEFAULT_PLAN_SHA)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--code-revision", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    store = _build_store(args.object_root)
    pages = load_pages(
        store,
        plan_sha=args.plan_sha,
        model=args.model,
        provider=args.provider,
    )
    if not pages:
        raise RuntimeError("no OCR evidence pages found for the requested plan/model/provider")

    report = analyze_evidence(
        pages,
        expected_model=args.model,
        expected_provider=args.provider,
    )
    report["provenance"] = {
        "plan_sha256": args.plan_sha,
        "model": args.model,
        "provider": args.provider,
        "object_root": str(args.object_root) if args.object_root else None,
        "code_revision": args.code_revision,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "analysis.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (args.output / "analysis.md").write_text(
        render_markdown(
            report,
            plan_sha=args.plan_sha,
            model=args.model,
            provider=args.provider,
            object_root=str(args.object_root) if args.object_root else None,
            code_revision=args.code_revision,
        ),
        encoding="utf-8",
    )
    print(json.dumps({k: report[k] for k in ("page_count", "change_taxonomy", "runtime")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
