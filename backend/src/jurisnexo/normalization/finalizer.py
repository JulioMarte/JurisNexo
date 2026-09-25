from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jurisnexo.acquisition.official_corpus import ObjectStore
from jurisnexo.normalization.manifest import (
    NormalizationManifestItem,
    build_normalization_manifest,
    publish_normalization_manifest,
)
from jurisnexo.normalization.planner import NormalizationPlan
from jurisnexo.normalization.reconciliation import (
    ReconciliationSnapshot,
    reconcile_normalization,
)
from jurisnexo.normalization.repository import RunReconciliationState, RunSummary


class FinalizationLedger(Protocol):
    def resolve_source_artifact_id(self, *, scope_id: str, sha256: str) -> str: ...

    def reconciliation_state(
        self,
        *,
        scope_id: str,
        run_id: str,
    ) -> RunReconciliationState: ...

    def summarize_run(self, *, scope_id: str, run_id: str) -> RunSummary: ...

    def reserve_manifest_published_at(
        self,
        *,
        scope_id: str,
        run_id: str,
    ) -> datetime: ...

    def persist_manifest(
        self,
        *,
        scope_id: str,
        run_id: str,
        sha256: str,
        storage_locator: str,
        byte_size: int,
        summary: RunSummary,
    ) -> str: ...

    def close_run(self, *, scope_id: str, run_id: str) -> RunSummary: ...

    def fail_run(
        self,
        *,
        scope_id: str,
        run_id: str,
        reason: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class FinalizationResult:
    run_id: str
    manifest_sha256: str
    manifest_object_key: str
    manifest_record_id: str
    status: str


@dataclass(slots=True)
class NormalizationFinalizer:
    ledger: FinalizationLedger
    object_store: ObjectStore

    def finalize(
        self,
        *,
        plan: NormalizationPlan,
        run_id: str,
        scope_id: str,
        pipeline_version: str,
        config_sha256: str,
    ) -> FinalizationResult:
        state = self.ledger.reconciliation_state(
            scope_id=scope_id,
            run_id=run_id,
        )
        planned_ids = frozenset(
            self.ledger.resolve_source_artifact_id(
                scope_id=scope_id,
                sha256=item.source_sha256,
            )
            for item in plan.items
            if item.source_sha256 is not None
            and item.disposition in {"normalize", "reuse"}
        )

        storage_present = frozenset(
            artifact_id
            for artifact_id, key in state.artifact_storage_keys.items()
            if self.object_store.exists(key)
        )
        failed_sources = frozenset(
            item.source_artifact_id
            for item in state.items
            if item.status in {"failed", "skipped"}
        )
        report = reconcile_normalization(
            ReconciliationSnapshot(
                planned_source_ids=planned_ids,
                run_item_source_ids=state.run_item_source_ids,
                referenced_artifact_ids=state.referenced_artifact_ids,
                lineage_artifact_ids=state.lineage_artifact_ids,
                storage_artifact_ids=storage_present,
                quality_report_source_ids=(
                    state.quality_report_source_ids | failed_sources
                ),
            )
        )
        if not report.can_close:
            self.ledger.fail_run(
                scope_id=scope_id,
                run_id=run_id,
                reason=(
                    "normalization reconciliation failed: "
                    f"missing_run_items={report.missing_run_items}; "
                    f"unexpected_run_items={report.unexpected_run_items}; "
                    f"missing_lineage={report.missing_lineage}; "
                    f"missing_storage={report.missing_storage}; "
                    f"missing_quality_reports={report.missing_quality_reports}"
                ),
            )
            raise RuntimeError("normalization reconciliation failed")

        summary = self.ledger.summarize_run(scope_id=scope_id, run_id=run_id)
        published_at = self.ledger.reserve_manifest_published_at(
            scope_id=scope_id,
            run_id=run_id,
        )
        manifest = build_normalization_manifest(
            run_id=run_id,
            pipeline_version=pipeline_version,
            config_sha256=config_sha256,
            input_manifest_sha256=plan.manifest_sha256,
            published_at=published_at,
            reconciliation=report,
            items=tuple(
                NormalizationManifestItem(
                    source_artifact_id=item.source_artifact_id,
                    status=item.status,
                    normalized_artifact_id=item.normalized_artifact_id,
                    quality_state=item.quality_state,
                )
                for item in state.items
            ),
        )
        stored = publish_normalization_manifest(
            object_store=self.object_store,
            manifest=manifest,
        )
        record_id = self.ledger.persist_manifest(
            scope_id=scope_id,
            run_id=run_id,
            sha256=stored.sha256,
            storage_locator=stored.object_key,
            byte_size=stored.byte_count,
            summary=summary,
        )
        closed = self.ledger.close_run(scope_id=scope_id, run_id=run_id)
        status = (
            "succeeded"
            if closed.failed_count == 0 and closed.review_required_count == 0
            else "completed_with_errors"
        )
        return FinalizationResult(
            run_id=run_id,
            manifest_sha256=stored.sha256,
            manifest_object_key=stored.object_key,
            manifest_record_id=record_id,
            status=status,
        )
