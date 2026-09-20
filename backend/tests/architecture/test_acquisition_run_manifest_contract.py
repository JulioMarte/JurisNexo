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



def test_large_document_backfills_require_durable_recovery_contract() -> None:
    scripts_dir = REPO_ROOT / "backend" / "scripts"
    offenders: list[str] = []

    for path in sorted(scripts_dir.glob("*backfill*.py")):
        if "canary" in path.name:
            continue
        text = path.read_text(encoding="utf-8")
        if "acquire_candidates(" not in text:
            continue
        required = (
            "AcquisitionRecoveryJournal",
            "S3RecoveryCheckpointMirror",
            "checkpoint_identity=",
            "classify_infrastructure_error",
            "signal.SIGTERM",
            "signal.SIGINT",
            "raise SystemExit(main())",
        )
        missing = [marker for marker in required if marker not in text]
        if missing:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)} missing {', '.join(missing)}"
            )

    assert not offenders, (
        "Large production document backfills must preserve incremental durable recovery "
        "state scoped to an explicit checkpoint identity, classify infrastructure failures "
        "separately from document failures, handle normal termination signals, and terminate "
        "expected interruptions through controlled exit codes. Violations: "
        f"{offenders}"
    )
