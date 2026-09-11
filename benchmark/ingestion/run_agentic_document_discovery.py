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
from jurisnexo.ingestion.document_environment import DocumentEnvironment
from jurisnexo.model_providers.google_gemini import GoogleGeminiProvider

_MAX_INPUT_CHARS = 500_000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded multi-step document discovery")
    parser.add_argument("--input", type=Path, required=True)
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
    parser.add_argument("--max-model-calls", type=int, default=6)
    parser.add_argument("--max-total-tokens", type=int, default=24_000)
    parser.add_argument("--decision-max-output-tokens", type=int, default=1024)
    parser.add_argument("--synthesis-max-output-tokens", type=int, default=4096)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required; configure it as a GitHub secret")

    raw = args.input.read_text(encoding="utf-8")
    if len(raw) > _MAX_INPUT_CHARS:
        raise SystemExit(
            f"Input has {len(raw)} characters; maximum for this benchmark is {_MAX_INPUT_CHARS}"
        )

    pages = tuple(part.strip() for part in raw.split("\f") if part.strip())
    if not pages:
        raise SystemExit("Input contains no non-empty pages")

    provider = GoogleGeminiProvider(
        api_key=api_key,
        model=args.model,
        service_tier=args.service_tier,
    )
    environment = DocumentEnvironment(pages)
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
        ),
    )

    payload = {
        "provider": result.synthesis_result.provider,
        "model": result.synthesis_result.model,
        "model_version": result.synthesis_result.model_version,
        "service_tier": args.service_tier,
        "environment": {
            "page_count": environment.page_count,
            "description": environment.describe(),
        },
        "budget": {
            "max_model_calls": args.max_model_calls,
            "max_total_tokens": args.max_total_tokens,
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
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
