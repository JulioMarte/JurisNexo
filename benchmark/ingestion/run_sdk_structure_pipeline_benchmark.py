from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from agents import set_tracing_disabled

from jurisnexo.ingestion.artifact_inspection import (
    build_artifact_inspection_profile,
    parse_pdfimages_page_numbers,
)
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.ingestion.logical_document_view import (
    build_document_environment_from_logical_view,
    materialize_logical_document_view,
)
from jurisnexo.ingestion.scanned_page_materialization import (
    PhysicalPageLayout,
    detect_adjacent_duplicate_scans,
    parse_bbox_layout,
    sanitize_bbox_layout_xml,
)
from jurisnexo.ingestion.sdk_structure_agent import (
    StructureInvestigationBudgetExceeded,
    StructureInvestigationFailed,
    run_structure_agent,
)
from jurisnexo.ingestion.sdk_structure_auditor import run_structure_auditor
from jurisnexo.ingestion.structure_trace import ArtifactInspectionProfile, StructureToolTraceEvent
from jurisnexo.model_providers.agents_sdk_compatible import (
    CompatibleProviderName,
    build_compatible_model_provider,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the production Structure Agent and adversarial auditor over one real artifact"
        )
    )
    parser.add_argument("--bbox", type=Path, required=True)
    parser.add_argument("--pdfimages-list", type=Path, required=True)
    parser.add_argument("--structure-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--trace-output", type=Path, required=True)
    parser.add_argument("--artifact-label", required=True)
    parser.add_argument("--provider", choices=("gemini", "deepseek"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--structure-max-turns", type=int, default=128)
    parser.add_argument("--audit-max-turns", type=int, default=96)
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
) -> tuple[DocumentEnvironment, tuple[PhysicalPageLayout, ...], dict[str, object]]:
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
    return environment, physical_pages, document_view


def _serialize_trace(events: tuple[StructureToolTraceEvent, ...]) -> list[dict[str, object]]:
    return [event.model_dump(mode="json") for event in events]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _journal_path(args: argparse.Namespace) -> Path:
    return args.trace_output.with_suffix(".jsonl")


def _write_budget_failure(
    *,
    args: argparse.Namespace,
    exc: StructureInvestigationBudgetExceeded,
    profile: ArtifactInspectionProfile,
) -> None:
    payload = {
        "status": "BUDGET_EXHAUSTED",
        "stage": exc.stage,
        "max_turns": exc.max_turns,
        "tool_call_count": len(exc.tool_trace),
        "artifact_profile": profile.model_dump(mode="json"),
        "tool_trace": _serialize_trace(exc.tool_trace),
        "journal_path": str(_journal_path(args)),
    }
    _write_json(args.trace_output, payload)
    _write_json(args.trace_output.with_name("structure-pipeline-error.json"), payload)


def _write_runtime_failure(
    *,
    args: argparse.Namespace,
    exc: StructureInvestigationFailed,
    profile: ArtifactInspectionProfile,
) -> None:
    payload = {
        "status": "RUNTIME_FAILURE",
        "stage": exc.stage,
        "error_type": exc.error_type,
        "error_message": exc.error_message,
        "tool_call_count": len(exc.tool_trace),
        "artifact_profile": profile.model_dump(mode="json"),
        "tool_trace": _serialize_trace(exc.tool_trace),
        "journal_path": str(_journal_path(args)),
    }
    _write_json(args.trace_output, payload)
    _write_json(args.trace_output.with_name("structure-pipeline-error.json"), payload)


async def _run(args: argparse.Namespace) -> None:
    provider_name: CompatibleProviderName = args.provider
    provider = build_compatible_model_provider(
        provider=provider_name,
        api_key=_api_key(provider_name),
    )
    environment, physical_pages, document_view = _materialize_environment(
        bbox=args.bbox,
        minimum_region_characters=args.minimum_region_characters,
    )
    image_pages = parse_pdfimages_page_numbers(
        args.pdfimages_list.read_text(encoding="utf-8", errors="replace")
    )
    profile = build_artifact_inspection_profile(
        physical_pages=physical_pages,
        image_page_numbers=image_pages,
    )
    journal_path = _journal_path(args)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.unlink(missing_ok=True)

    try:
        structure = await run_structure_agent(
            environment=environment,
            artifact_label=args.artifact_label,
            model=args.model,
            max_turns=args.structure_max_turns,
            max_tool_output_chars=args.max_tool_output_chars,
            search_max_hits=args.search_max_hits,
            artifact_profile=profile,
            model_provider=provider,
            trace_journal_path=journal_path,
        )
    except StructureInvestigationBudgetExceeded as exc:
        _write_budget_failure(args=args, exc=exc, profile=profile)
        raise
    except StructureInvestigationFailed as exc:
        _write_runtime_failure(args=args, exc=exc, profile=profile)
        raise

    structure_payload = {
        "provider": provider_name,
        "model": args.model,
        "document_view": document_view,
        "artifact_profile": profile.model_dump(mode="json"),
        "environment": {
            "page_count": environment.page_count,
            "description": environment.describe(),
            "supports_printed_page_lookup": environment.supports_printed_page_lookup,
        },
        "usage": {"total_tokens": structure.usage_total_tokens},
        "last_agent_name": structure.last_agent_name,
        "tool_call_count": len(structure.tool_trace),
        "hypothesis": structure.hypothesis.model_dump(mode="json"),
    }
    _write_json(args.structure_output, structure_payload)

    try:
        audit = await run_structure_auditor(
            environment=environment,
            hypothesis=structure.hypothesis,
            artifact_label=args.artifact_label,
            model=args.model,
            structure_agent_trace=structure.tool_trace,
            max_turns=args.audit_max_turns,
            max_tool_output_chars=args.max_tool_output_chars,
            search_max_hits=args.search_max_hits,
            artifact_profile=profile,
            model_provider=provider,
            trace_journal_path=journal_path,
        )
    except StructureInvestigationBudgetExceeded as exc:
        _write_budget_failure(args=args, exc=exc, profile=profile)
        raise
    except StructureInvestigationFailed as exc:
        _write_runtime_failure(args=args, exc=exc, profile=profile)
        raise

    audit_payload = {
        "provider": provider_name,
        "model": args.model,
        "usage": {"total_tokens": audit.usage_total_tokens},
        "last_agent_name": audit.last_agent_name,
        "tool_call_count": len(audit.tool_trace),
        "audit": audit.audit.model_dump(mode="json"),
    }
    _write_json(args.audit_output, audit_payload)
    _write_json(
        args.trace_output,
        {
            "status": "COMPLETE",
            "artifact_profile": profile.model_dump(mode="json"),
            "journal_path": str(journal_path),
            "structure_agent": {
                "tool_call_count": len(structure.tool_trace),
                "tool_trace": _serialize_trace(structure.tool_trace),
            },
            "structure_auditor": {
                "tool_call_count": len(audit.tool_trace),
                "tool_trace": _serialize_trace(audit.tool_trace),
            },
        },
    )


def main() -> None:
    args = _parse_args()
    set_tracing_disabled(True)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()