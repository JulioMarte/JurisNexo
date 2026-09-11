from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from jurisnexo.ingestion.agentic_document_discovery import (
    DiscoveryBudget,
    run_agentic_document_discovery,
)
from jurisnexo.ingestion.context_governor import ContextPolicy
from jurisnexo.ingestion.logical_document_view import (
    build_document_environment_from_logical_view,
    materialize_logical_document_view,
)
from jurisnexo.ingestion.scanned_page_materialization import (
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
    sanitize_bbox_layout_xml,
)
from jurisnexo.model_providers.google_gemini import GoogleGeminiProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run token-governed agentic discovery over a scanned PDF bbox representation"
    )
    parser.add_argument("--bbox", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-label", required=True)
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "gemini-3.8-flash"))
    parser.add_argument(
        "--service-tier",
        choices=("flex", "standard", "priority"),
        default=os.getenv("LLM_SERVICE_TIER", "flex"),
    )
    parser.add_argument(
        "--thinking-level",
        choices=("low", "medium", "high"),
        default=os.getenv("LLM_THINKING_LEVEL", "medium"),
    )
    parser.add_argument("--max-model-calls", type=int, default=8)
    parser.add_argument("--max-total-tokens", type=int, default=40_000)
    parser.add_argument("--parent-context-soft-limit", type=int, default=120_000)
    parser.add_argument("--delegated-context-soft-limit", type=int, default=120_000)
    parser.add_argument("--decision-max-output-tokens", type=int, default=1024)
    parser.add_argument("--synthesis-max-output-tokens", type=int, default=4096)
    parser.add_argument("--minimum-region-characters", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required; configure it as a GitHub secret")

    raw_xml = args.bbox.read_text(encoding="utf-8", errors="replace")
    sanitized_xml, xml_replacement_count = sanitize_bbox_layout_xml(raw_xml)
    physical_pages = parse_bbox_layout(sanitized_xml)
    duplicate_scans = detect_adjacent_duplicate_scans(physical_pages)
    logical_view = materialize_logical_document_view(
        physical_pages=physical_pages,
        duplicate_scans=duplicate_scans,
        minimum_region_characters=args.minimum_region_characters,
    )
    environment = build_document_environment_from_logical_view(logical_view)

    provider = GoogleGeminiProvider(
        api_key=api_key,
        model=args.model,
        service_tier=args.service_tier,
    )
    context_policy = ContextPolicy(
        parent_soft_limit_tokens=args.parent_context_soft_limit,
        delegated_soft_limit_tokens=args.delegated_context_soft_limit,
    )
    result = run_agentic_document_discovery(
        provider=provider,
        environment=environment,
        artifact_label=args.artifact_label,
        thinking_level=args.thinking_level,
        decision_max_output_tokens=args.decision_max_output_tokens,
        synthesis_max_output_tokens=args.synthesis_max_output_tokens,
        budget=DiscoveryBudget(
            max_model_calls=args.max_model_calls,
            max_total_tokens=args.max_total_tokens,
            context_policy=context_policy,
        ),
    )

    payload = {
        "provider": result.synthesis_result.provider,
        "model": result.synthesis_result.model,
        "model_version": result.synthesis_result.model_version,
        "service_tier": args.service_tier,
        "document_view": {
            "physical_page_count": len(physical_pages),
            "duplicate_scan_count": len(duplicate_scans),
            "scan_group_count": logical_view.scan_group_count,
            "view_page_count": len(logical_view.pages),
            "resolved_printed_page_count": logical_view.resolved_printed_page_count,
            "dominant_printed_page_offset": logical_view.dominant_printed_page_offset,
            "xml_forbidden_control_character_count": xml_replacement_count,
        },
        "environment": {
            "page_count": environment.page_count,
            "description": environment.describe(),
            "supports_printed_page_lookup": environment.supports_printed_page_lookup,
        },
        "budget": {
            "max_model_calls": args.max_model_calls,
            "max_total_tokens": args.max_total_tokens,
            "parent_context_soft_limit_tokens": args.parent_context_soft_limit,
            "delegated_context_soft_limit_tokens": args.delegated_context_soft_limit,
        },
        "usage": asdict(result.usage),
        "steps": [
            {
                "step_number": step.step_number,
                "model": step.model_result.model,
                "decision": step.decision.model_dump(mode="json"),
                "tool_output": step.tool_output,
                "usage": asdict(step.model_result.usage),
                "response_id": step.model_result.response_id,
            }
            for step in result.steps
        ],
        "synthesis_response_id": result.synthesis_result.response_id,
        "hypothesis": result.hypothesis.model_dump(mode="json"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
