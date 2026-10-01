from __future__ import annotations

import os
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

PROVIDER_SECRET_MARKERS = (
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_root_agent_map_defines_edit_safe_and_explicit_live_execution() -> None:
    agents = _read(REPO_ROOT / "AGENTS.md")
    for phrase in (
        "AUTO / EDIT-SAFE",
        "EXPLICIT / LIVE",
        "A path filter alone is not consent to spend tokens",
        "Never treat presence of an API key or secret as permission to call a provider",
    ):
        assert phrase in agents, f"AGENTS.md lost benchmark execution safety rule: {phrase!r}"


def test_provider_workflows_with_pr_sync_have_explicit_live_gate() -> None:
    violations: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _read(path)
        if "pull_request:" not in workflow:
            continue
        if not any(marker in workflow for marker in PROVIDER_SECRET_MARKERS):
            continue
        if "synchronize" not in workflow:
            continue

        has_dispatch_gate = "github.event_name == 'workflow_dispatch'" in workflow
        has_deliberate_label_gate = (
            "github.event.pull_request.labels" in workflow
            or "github.event.label.name" in workflow
        )
        if not has_dispatch_gate:
            violations.append(f"{path.name}: provider-capable PR workflow lacks workflow_dispatch job gate")
        if not has_deliberate_label_gate and "if: github.event_name == 'workflow_dispatch'" not in workflow:
            violations.append(f"{path.name}: provider-capable PR workflow lacks explicit label/manual gate")

    assert not violations, (
        "Ordinary PR synchronization must not be sufficient authorization for provider/token spend:\n"
        + "\n".join(violations)
    )


def test_open_source_ocr_bakeoff_keeps_contract_auto_but_heavy_pdf_work_explicit() -> None:
    workflow = _read(WORKFLOWS / "scj-open-source-ocr-bakeoff.yml")

    assert "types: [opened, synchronize, reopened, labeled]" in workflow
    assert "contract:\n    runs-on:" in workflow
    assert (
        "prepare:\n"
        "    if: github.event_name == 'workflow_dispatch' || "
        "github.event.label.name == 'ocr-bakeoff-live'\n"
        in workflow
    )
    assert "engine:\n    needs: prepare" in workflow
    assert "aggregate:\n    needs: [prepare, engine]" in workflow
