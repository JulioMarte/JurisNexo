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



def test_scj_corpus_backfill_discovers_source_scope_and_preserves_no_locator_records() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "scj-1994-full-storage-backfill.yml"
    ).read_text(encoding="utf-8")
    inventory = (REPO_ROOT / "backend" / "scripts" / "scj_year_inventory.py").read_text(
        encoding="utf-8"
    )
    merger = (
        REPO_ROOT / "backend" / "scripts" / "merge_scj_1994_inventory.py"
    ).read_text(encoding="utf-8")

    assert "SCJ_YEAR_MIN:" not in workflow
    assert "SCJ_YEAR_MAX:" not in workflow
    assert "scj_decision_year_discovery.py" in workflow
    assert "fromJSON(needs.discover_years.outputs.active_years)" in workflow
    assert "SCJ_YEAR: ${{ matrix.year }}" in workflow
    assert "persist_scj_certified_inventory.py" in workflow
    assert "name: Validate production S3 write access" in workflow
    assert "needs: storage-smoke" in workflow
    assert workflow.index("  storage-smoke:") < workflow.index("  discover_years:")
    assert "SCJ_YEAR_DISCOVERY_DIR: ${{ runner.temp }}/scj-year-discovery" in workflow
    assert (
        "SCJ_YEAR_DISCOVERY_OUTPUT: "
        "${{ runner.temp }}/scj-year-discovery/scj-year-discovery.json"
    ) in workflow
    assert 'path: ${{ runner.temp }}/scj-year-discovery/' in workflow
    assert (
        "SCJ_YEAR_DISCOVERY_FILE: "
        "${{ runner.temp }}/scj-year-discovery/scj-year-discovery.json"
    ) in workflow

    assert 'f"decisions\\t{expediente_id}\\t{guid}\\t{url}"' not in inventory
    assert '"no_locator"' in inventory
    assert "official_record_has_no_download_url" in inventory
    assert "locator_present_source_record_count" in merger
    assert "no_locator_source_record_count" in merger



def test_production_backfills_remain_source_scoped_and_acquisition_only() -> None:
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    offenders: list[str] = []

    for path in sorted(workflows_dir.glob("*backfill*.yml")):
        text = path.read_text(encoding="utf-8")
        has_scj = "SCJ_" in text or "scj_" in text
        has_tc = "TC_" in text or "tc_" in text
        if has_scj and has_tc:
            offenders.append(f"{path.name}: mixes SCJ and TC acquisition")

    scj_workflow = (
        workflows_dir / "scj-1994-full-storage-backfill.yml"
    ).read_text(encoding="utf-8")
    forbidden_scj_markers = (
        "DATABASE_URL",
        "register_scj_source_inventory.py",
        "link_source_documents_to_artifacts.py",
        "tc_inventory.py",
        "tc_backfill_shard.py",
    )
    for marker in forbidden_scj_markers:
        if marker in scj_workflow:
            offenders.append(
                "scj-1994-full-storage-backfill.yml: "
                f"contains downstream or cross-source marker {marker}"
            )

    assert not offenders, (
        "Production acquisition workflows must stay source-scoped and must not combine "
        "artifact acquisition with PostgreSQL registration/linking or another court. "
        f"Violations: {offenders}"
    )



def test_scj_reconciliation_does_not_treat_historical_storage_residue_as_snapshot_failure() -> None:
    verifier = (
        REPO_ROOT / "backend" / "scripts" / "verify_scj_1994_storage_backfill.py"
    ).read_text(encoding="utf-8")

    assert "missing_objects = sorted(object_keys - stored_keys)" in verifier
    assert "if missing_objects:" in verifier
    assert (
        "unreferenced_storage_objects = sorted(stored_keys - all_manifest_object_keys)"
        in verifier
    )
    assert '"unreferenced_storage_object_count"' in verifier
    assert "unreferenced-storage-objects.json" in verifier
    assert (
        "storage contains {len(orphan_objects)} unreferenced SCJ decision objects"
        not in verifier
    )
