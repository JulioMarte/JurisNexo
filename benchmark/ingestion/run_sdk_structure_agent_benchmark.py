from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from agents import RunConfig, Runner, set_tracing_disabled

from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.logical_document_view import (
    build_document_environment_from_logical_view,
    materialize_logical_document_view,
)
from jurisnexo.ingestion.scanned_page_materialization import (
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
    sanitize_bbox_layout_xml,
)
from jurisnexo.ingestion.sdk_structure_agent import (
    StructureAgentContext,
    build_structure_agent,
)
from jurisnexo.ingestion.evidence_validation import validate_index_reference_evidence
from jurisnexo.model_providers.agents_sdk_compatible import (
    CompatibleProviderName,
    build_compatible_model_provider,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production Structure Agent over a real scanned-document workspace"
    )
    parser.add_argument("--bbox", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-label", required=True)
    parser.add_argument("--provider", choices=("gemini", "deepseek"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-turns", type=int, default=16)
    parser.add_argument("--max-tool-output-chars", type=int, default=60_000)
    parser.add_argument("--search-max-hits", type=int, default=20)
    parser.add_argument("--minimum-region-characters", type=int, default=80)
    return parser.parse_args()


def _api_key(provider: CompatibleProviderName) -> str:
    variable = "GEMINI_API_KEY" if provider == "gemini" else "DEEPSEEK_API_KEY"
    value = os.getenv(variable, "")
    if not value:
        raise SystemExit(f"{variable} is required")
    return value


def _materialize_environment(
    *, bbox: Path, minimum_region_characters: int
) -> tuple[DocumentEnvironment, dict[str, object]]:
    raw_xml = bbox.read_text(encoding="utf-8", errors="replace")
    sanitized_xml, xml_replacement_count = sanitize_bbox_layout_xml(raw_xml)
    physical_pages = parse_bbox_layout(sanitized_xml)
    duplicate_scans = detect_adjacent_duplicate_scans(physical_pages)
    logical_view = materialize_logical_document_view(
        physical_pages=physical_pages,
        duplicate_scans=duplicate_scans,
        minimum_region_characters=minimum_region_characters,
    )
    environment = build_document_environment_from_logical_view(logical_view)
    document_view: dict[str, object] = {
        "physical_page_count": len(physical_pages),
        "duplicate_scan_count": len(duplicate_scans),
        "scan_group_count": logical_view.scan_group_count,
        "view_page_count": len(logical_view.pages),
        "resolved_printed_page_count": logical_view.resolved_printed_page_count,
        "dominant_printed_page_offset": logical_view.dominant_printed_page_offset,
        "xml_forbidden_control_character_count": xml_replacement_count,
    }
    return environment, document_view


async def _run(args: argparse.Namespace) -> dict[str, object]:
    provider_name: CompatibleProviderName = args.provider
    provider = build_compatible_model_provider(
        provider=provider_name,
        api_key=_api_key(provider_name),
    )
    environment, document_view = _materialize_environment(
        bbox=args.bbox,
        minimum_region_characters=args.minimum_region_characters,
    )
    context = StructureAgentContext(
        environment=environment,
        max_tool_output_chars=args.max_tool_output_chars,
        search_max_hits=args.search_max_hits,
    )
    agent = build_structure_agent(model=args.model)
    initial_page = environment.get_page(1)
    prompt = (
        f"Artifact: {args.artifact_label}\n"
        f"Environment: {environment.describe()}\n\n"
        f"Initial page preview (view_page=1, printed_page={initial_page.printed_page_number}):\n"
        f"{initial_page.text}\n\n"
        "Investigate the structure conservatively. Use tools whenever needed before finalizing. "
        "When an index destination does not match, investigate nearby printed pages and preserve "
        "the source claim separately from the observed start."
    )
    result = await Runner.run(
        starting_agent=agent,
        input=prompt,
        context=context,
        max_turns=args.max_turns,
        run_config=RunConfig(
            workflow_name="JurisNexo Real Document Structure Benchmark",
            trace_include_sensitive_data=False,
            model_provider=provider,
        ),
    )
    hypothesis = result.final_output_as(
        agent.output_type,
        raise_if_incorrect_type=True,
    )
    validate_index_reference_evidence(hypothesis=hypothesis, environment=environment)
    return {
        "provider": provider_name,
        "model": args.model,
        "document_view": document_view,
        "environment": {
            "page_count": environment.page_count,
            "description": environment.describe(),
            "supports_printed_page_lookup": environment.supports_printed_page_lookup,
        },
        "usage": {
            "requests": result.context_wrapper.usage.requests,
            "input_tokens": result.context_wrapper.usage.input_tokens,
            "output_tokens": result.context_wrapper.usage.output_tokens,
            "total_tokens": result.context_wrapper.usage.total_tokens,
        },
        "last_agent_name": result.last_agent.name,
        "hypothesis": hypothesis.model_dump(mode="json"),
    }


def main() -> None:
    args = _parse_args()
    set_tracing_disabled(True)
    try:
        payload = asyncio.run(_run(args))
    except Exception as exc:
        error_path = args.output.with_name("sdk-structure-agent-error.json")
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            json.dumps(
                {
                    "status": "ERROR",
                    "provider": args.provider,
                    "model": args.model,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
