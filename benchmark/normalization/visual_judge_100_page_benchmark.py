from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.model_providers.openrouter_visual import OpenRouterVisualModelProvider
from jurisnexo.normalization.visual_identifier_benchmark import (
    select_verification_target,
    visible_token_is_exact,
)

PAGE_LIMIT = int(os.environ.get("VISUAL_JUDGE_PAGE_LIMIT", "1"))
OUTPUT = Path(
    os.environ.get("VISUAL_JUDGE_OUTPUT", "visual-judge-100-page-output")
)
PREPARED_MANIFEST = Path(
    os.environ.get(
        "VISUAL_JUDGE_PREPARED_MANIFEST",
        "prepared-manifest.json",
    )
)
MAX_COST_USD = float(os.environ.get("VISUAL_JUDGE_MAX_COST_USD", "1.0"))
MODEL = os.environ["VISUAL_JUDGE_MODEL"]
PROVIDER = os.environ["VISUAL_JUDGE_PROVIDER"]
REASONING = os.environ.get("VISUAL_JUDGE_REASONING", "high")
STRUCTURED_MODE = os.environ.get("VISUAL_JUDGE_STRUCTURED_MODE", "tool")
MAX_OUTPUT_TOKENS = int(
    os.environ.get("VISUAL_JUDGE_MAX_OUTPUT_TOKENS", "256")
)


@dataclass(frozen=True, slots=True)
class PageCase:
    sample_id: str
    object_key: str
    page_index: int
    case_kind: str
    original_token: str
    candidate_token: str
    expected_matches: bool
    image_path: str


@dataclass(frozen=True, slots=True)
class PageResult:
    sample_id: str
    object_key: str
    page_index: int
    case_kind: str
    original_token: str
    candidate_token: str
    expected_matches: bool
    observed_matches: bool
    observed_visible_token: str | None
    match_decision_correct: bool
    visible_token_exact: bool
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    routed_provider: str


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "matches": {"type": "boolean"},
            "visible_token": {"type": ["string", "null"]},
        },
        "required": ["matches", "visible_token"],
        "additionalProperties": False,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_prepared_pages() -> list[tuple[PageCase, bytes]]:
    manifest = json.loads(PREPARED_MANIFEST.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("prepared manifest has no cases")
    admission = manifest.get("reference_admission")
    if not isinstance(admission, dict):
        raise RuntimeError("prepared manifest has no reference_admission")
    if admission.get("kind") != "dual_channel_visual_native":
        raise RuntimeError("visual judge requires dual-channel admitted references")

    root = PREPARED_MANIFEST.parent
    selected = cases[:PAGE_LIMIT]
    if len(selected) != PAGE_LIMIT:
        raise RuntimeError(
            f"requested {PAGE_LIMIT} admitted pages but manifest has "
            f"{len(selected)}"
        )

    paired: list[tuple[PageCase, bytes]] = []
    for row_index, raw in enumerate(selected):
        if not isinstance(raw, dict):
            raise RuntimeError("prepared manifest case is not an object")
        if raw.get("reference_authority") != "dual_channel_aligned":
            raise RuntimeError("visual judge case is not dual-channel aligned")
        if raw.get("reference_reliable") is not True:
            raise RuntimeError("visual judge case reference is not reliable")

        reference_path = root / str(raw["reference_path"])
        image_path = root / str(raw["image_path"])
        reference = reference_path.read_text(encoding="utf-8")
        image = image_path.read_bytes()
        if _sha256(reference.encode("utf-8")) != str(raw["reference_sha256"]):
            raise RuntimeError("prepared reference hash mismatch")
        if _sha256(image) != str(raw["image_sha256"]):
            raise RuntimeError("prepared image hash mismatch")

        target = select_verification_target(reference)
        if target is None:
            raise RuntimeError(
                f"admitted page {raw.get('sample_id')} has no verification token"
            )
        original, corrupted = target
        base_id = str(raw.get("sample_id") or f"case-{row_index:04d}")
        common = {
            "object_key": str(raw["object_key"]),
            "page_index": int(raw["page_index"]),
            "original_token": original,
            "image_path": str(raw["image_path"]),
        }
        paired.append(
            (
                PageCase(
                    sample_id=f"{base_id}-clean",
                    case_kind="clean",
                    candidate_token=original,
                    expected_matches=True,
                    **common,
                ),
                image,
            )
        )
        paired.append(
            (
                PageCase(
                    sample_id=f"{base_id}-corrupted",
                    case_kind="controlled_corruption",
                    candidate_token=corrupted,
                    expected_matches=False,
                    **common,
                ),
                image,
            )
        )
    return paired


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> int:
    if PAGE_LIMIT <= 0 or PAGE_LIMIT > 100:
        raise ValueError("VISUAL_JUDGE_PAGE_LIMIT must be between 1 and 100")
    if MAX_COST_USD <= 0 or MAX_COST_USD > 2:
        raise ValueError("VISUAL_JUDGE_MAX_COST_USD must be >0 and <=2")
    if STRUCTURED_MODE not in {
        "tool",
        "json_schema",
        "json_object",
        "prompt_json",
    }:
        raise ValueError("unsupported VISUAL_JUDGE_STRUCTURED_MODE")
    if MAX_OUTPUT_TOKENS < 64 or MAX_OUTPUT_TOKENS > 4096:
        raise ValueError(
            "VISUAL_JUDGE_MAX_OUTPUT_TOKENS must be between 64 and 4096"
        )

    openrouter = get_openrouter_settings()
    if openrouter.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    pages = _load_prepared_pages()

    provider = OpenRouterVisualModelProvider(
        api_key=openrouter.api_key.get_secret_value(),
        model=MODEL,
        base_url=openrouter.base_url,
        reasoning_effort=REASONING,
        structured_mode=STRUCTURED_MODE,
        provider_order=(PROVIDER,),
        allow_provider_fallbacks=False,
    )
    results: list[PageResult] = []
    running_cost = 0.0
    for case, image in pages:
        started = time.perf_counter()
        result = provider.verify_image_text(
            image=image,
            media_type="image/png",
            prompt=(
                "Read the legal-document page image itself. Locate the exact "
                "visible token referred to by CANDIDATE_TOKEN. Return "
                "matches=true only if the visible token is character-for-"
                "character identical to CANDIDATE_TOKEN. Always return "
                "visible_token as the exact token you see in the image; use "
                "null only if you genuinely cannot locate it. Do not infer, "
                "repair, normalize, or substitute from context.\n\n"
                f"CANDIDATE_TOKEN: {case.candidate_token}"
            ),
            json_schema=_schema(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        running_cost += result.cost_usd or 0.0
        if running_cost > MAX_COST_USD:
            raise RuntimeError(
                f"benchmark exceeded cost cap: ${running_cost:.6f}"
            )
        observed_matches = bool(result.value.get("matches", False))
        observed_visible = result.value.get("visible_token")
        observed_visible_token = (
            observed_visible if isinstance(observed_visible, str) else None
        )
        exact = visible_token_is_exact(
            expected_visible_token=case.original_token,
            observed_visible_token=observed_visible,
        )
        results.append(
            PageResult(
                sample_id=case.sample_id,
                object_key=case.object_key,
                page_index=case.page_index,
                case_kind=case.case_kind,
                original_token=case.original_token,
                candidate_token=case.candidate_token,
                expected_matches=case.expected_matches,
                observed_matches=observed_matches,
                observed_visible_token=observed_visible_token,
                match_decision_correct=(
                    observed_matches == case.expected_matches
                ),
                visible_token_exact=exact,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                thinking_tokens=result.usage.thinking_tokens,
                cost_usd=result.cost_usd,
                latency_ms=int((time.perf_counter() - started) * 1000),
                routed_provider=str(
                    result.provider_metadata.get("routed_provider") or ""
                ),
            )
        )

    clean = [item for item in results if item.expected_matches]
    corrupted = [item for item in results if not item.expected_matches]
    false_corrections = sum(not item.observed_matches for item in clean)
    detected_corruptions = sum(
        not item.observed_matches for item in corrupted
    )
    localized_corruptions = sum(
        (not item.observed_matches) and item.visible_token_exact
        for item in corrupted
    )
    clean_exact = sum(
        item.observed_matches and item.visible_token_exact for item in clean
    )
    pairs: dict[tuple[str, int], list[PageResult]] = {}
    for item in results:
        pairs.setdefault((item.object_key, item.page_index), []).append(item)
    fully_correct_pairs = sum(
        len(pair) == 2
        and all(item.match_decision_correct for item in pair)
        and all(item.visible_token_exact for item in pair)
        for pair in pairs.values()
    )

    costs = [item.cost_usd for item in results if item.cost_usd is not None]
    latencies = [item.latency_ms for item in results]
    payload = {
        "schema_version": 2,
        "benchmark_kind": "paired_visual_token_verification",
        "reference_status": "dual_channel_aligned",
        "model": MODEL,
        "pinned_provider": PROVIDER,
        "structured_mode": STRUCTURED_MODE,
        "reasoning_effort": REASONING,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "source_page_count": len(pairs),
        "verification_case_count": len(results),
        "clean_case_count": len(clean),
        "controlled_corruption_count": len(corrupted),
        "false_correction_rate": _rate(false_corrections, len(clean)),
        "clean_exact_confirmation_rate": _rate(clean_exact, len(clean)),
        "corruption_detection_recall": _rate(
            detected_corruptions,
            len(corrupted),
        ),
        "corruption_localization_recall": _rate(
            localized_corruptions,
            len(corrupted),
        ),
        "fully_correct_pair_rate": _rate(
            fully_correct_pairs,
            len(pairs),
        ),
        "match_decision_accuracy": _rate(
            sum(item.match_decision_correct for item in results),
            len(results),
        ),
        "visible_token_exact_rate": _rate(
            sum(item.visible_token_exact for item in results),
            len(results),
        ),
        "observed_cost_usd": running_cost,
        "mean_cost_per_verification_usd": (
            sum(costs) / len(costs) if costs else None
        ),
        "mean_cost_per_source_page_usd": (
            sum(costs) / len(pairs) if costs and pairs else None
        ),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "input_tokens": sum(item.input_tokens or 0 for item in results),
        "output_tokens": sum(item.output_tokens or 0 for item in results),
        "thinking_tokens": sum(item.thinking_tokens or 0 for item in results),
        "results": [asdict(item) for item in results],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
