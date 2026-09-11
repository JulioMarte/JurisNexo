from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from jurisnexo.ingestion.document_discovery import (
    DiscoveryRequest,
    discover_document_structure,
)
from jurisnexo.model_providers.google_gemini import GoogleGeminiProvider

_MAX_INPUT_CHARS = 120_000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one bounded document-structure discovery call")
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
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required; configure it as a GitHub secret")

    raw = args.input.read_text(encoding="utf-8")
    if len(raw) > _MAX_INPUT_CHARS:
        raise SystemExit(
            f"Input has {len(raw)} characters; maximum for this bounded benchmark is "
            f"{_MAX_INPUT_CHARS}"
        )

    page_samples = tuple(part.strip() for part in raw.split("\f") if part.strip())
    if not page_samples:
        raise SystemExit("Input contains no non-empty page samples")

    provider = GoogleGeminiProvider(
        api_key=api_key,
        model=args.model,
        service_tier=args.service_tier,
    )
    result = discover_document_structure(
        provider=provider,
        request=DiscoveryRequest(
            artifact_label=args.artifact_label,
            page_samples=page_samples,
            max_output_tokens=args.max_output_tokens,
            thinking_level=args.thinking_level,
        ),
    )

    payload = {
        "provider": result.model_result.provider,
        "model": result.model_result.model,
        "model_version": result.model_result.model_version,
        "service_tier": args.service_tier,
        "response_id": result.model_result.response_id,
        "usage": asdict(result.model_result.usage),
        "hypothesis": result.hypothesis.model_dump(mode="json"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
