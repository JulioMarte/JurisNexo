from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_ocr_jev_triage.py"
    spec = importlib.util.spec_from_file_location("scj_ocr_jev_triage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_jev_state_contains_metrics_and_bounded_disagreement_context() -> None:
    module = _module()
    item = {
        "source_pdf_sha256": "a" * 64,
        "page_index": 17,
        "classification": "misaligned",
        "quality_route": "jev_review",
        "risk_reasons": ["native_ocr_disagreement"],
        "ocr_p10_confidence": 72.5,
        "diff_segments": [
            {
                "tag": "replace",
                "native_excerpt": "Sentencia SCJ-SS-22-1191",
                "ocr_excerpt": "Sentencia SCJ-SS-22-191",
            }
        ],
    }

    rendered = module._render_state(item)
    payload = json.loads(rendered)

    assert payload["metrics"]["classification"] == "misaligned"
    assert payload["metrics"]["ocr_p10_confidence"] == 72.5
    assert payload["disagreement_segments"][0]["native_excerpt"].endswith("1191")
    assert len(rendered) <= module.MAX_CONTEXT_CHARS_PER_RECORD


def test_empty_jev_queue_needs_no_provider_credentials(tmp_path: Path) -> None:
    module = _module()
    input_path = tmp_path / "empty.jsonl"
    input_path.write_text("", encoding="utf-8")
    output = tmp_path / "out"

    assert module.run(
        input_path=input_path,
        output=output,
        max_cost_usd=0.05,
        limit=None,
    ) == 0

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["candidate_count"] == 0
    assert summary["observed_cost_usd"] == 0.0
    assert (output / "deepseek-review.jsonl").read_text(encoding="utf-8") == ""
