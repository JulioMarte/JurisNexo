from __future__ import annotations

import os
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def test_document_upload_scripts_commit_durable_run_manifests() -> None:
    scripts_dir = REPO_ROOT / "backend" / "scripts"
    offenders: list[str] = []

    for path in sorted(scripts_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "acquire_candidates(" not in text:
            continue
        if "AcquisitionRunManifestBuilder" not in text or ".commit(object_store=" not in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Production scripts that call the canonical document uploader must close the run with "
        "an immutable acquisition run manifest. Missing manifest integration: "
        f"{offenders}"
    )
