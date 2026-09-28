from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.repository import (
    RunItemSnapshot,
    RunReconciliationState,
    RunSummary,
)


@dataclass
class _MemoryStore:
    objects: dict[str, bytes] = field(default_factory=lambda: {"artifact-key": b"artifact"})

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type, metadata
        if key in self.objects:
            raise AssertionError("immutable object overwrite")
        self.objects[key] = content


@dataclass
class _Ledger:
    state: RunReconciliationState
    summary: RunSummary
    failed_reason: str | None = None
    persisted: bool = False
    closed: bool = False

    def resolve_source_artifact_id(self, *, scope_id: str, sha256: str) -> str:
        del scope_id
        if sha256 != "a" * 64:
            raise KeyError(sha256)
        return "source-1"

    def reconciliation_state(
        self, *, scope_id: str, run_id: str
    ) -> RunReconciliationState:
        del scope_id, run_id
        return self.state

    def summarize_run(self, *, scope_id: str, run_id: str) -> RunSummary:
        del scope_id, run_id
        return self.summary

    def reserve_manifest_published_at(
        self,
        *,
        scope_id: str,
        run_id: str,
    ) -> datetime:
        del scope_id, run_id
        return datetime(2026, 9, 25, tzinfo=UTC)

    def persist_manifest(
        self,
        *,
        scope_id: str,
        run_id: str,
        sha256: str,
        storage_locator: str,
        byte_size: int,
        summary: RunSummary,
    ) -> str:
        del scope_id, run_id, sha256, storage_locator, byte_size, summary
        self.persisted = True
        return "manifest-record"

    def close_run(self, *, scope_id: str, run_id: str) -> RunSummary:
        del scope_id, run_id
        self.closed = True
        return self.summary

    def fail_run(self, *, scope_id: str, run_id: str, reason: str) -> None:
        del scope_id, run_id
        self.failed_reason = reason


def _plan() -> NormalizationPlan:
    return NormalizationPlan(
        manifest_sha256="b" * 64,
        pipeline_version="v1",
        config_sha256="c" * 64,
        items=(
            NormalizationPlanItem(
                source_identifier="fixture",
                source_sha256="a" * 64,
                object_key="source-key",
                content_type="application/pdf",
                disposition="normalize",
                idempotency_key="d" * 64,
            ),
        ),
    )


def _summary() -> RunSummary:
    return RunSummary(
        selected_count=1,
        normalized_count=1,
        review_required_count=0,
        failed_count=0,
        skipped_count=0,
        pending_count=0,
        running_count=0,
    )


def test_finalizer_publishes_manifest_only_after_all_authorities_reconcile() -> None:
    ledger = _Ledger(
        state=RunReconciliationState(
            run_item_source_ids=frozenset({"source-1"}),
            referenced_artifact_ids=frozenset({"artifact-1"}),
            lineage_artifact_ids=frozenset({"artifact-1"}),
            artifact_storage_keys={"artifact-1": "artifact-key"},
            quality_report_source_ids=frozenset({"source-1"}),
            items=(
                RunItemSnapshot(
                    source_artifact_id="source-1",
                    status="normalized",
                    normalized_artifact_id="artifact-1",
                    quality_state="reported",
                ),
            ),
        ),
        summary=_summary(),
    )
    result = NormalizationFinalizer(ledger=ledger, object_store=_MemoryStore()).finalize(
        plan=_plan(),
        run_id="run-1",
        scope_id="scope-1",
        pipeline_version="v1",
        config_sha256="c" * 64,
    )
    assert result.status == "succeeded"
    assert ledger.persisted
    assert ledger.closed
    assert ledger.failed_reason is None


def test_finalizer_fails_closed_when_storage_is_missing() -> None:
    ledger = _Ledger(
        state=RunReconciliationState(
            run_item_source_ids=frozenset({"source-1"}),
            referenced_artifact_ids=frozenset({"artifact-1"}),
            lineage_artifact_ids=frozenset({"artifact-1"}),
            artifact_storage_keys={"artifact-1": "missing-key"},
            quality_report_source_ids=frozenset({"source-1"}),
            items=(
                RunItemSnapshot(
                    source_artifact_id="source-1",
                    status="normalized",
                    normalized_artifact_id="artifact-1",
                    quality_state="reported",
                ),
            ),
        ),
        summary=_summary(),
    )
    with pytest.raises(RuntimeError, match="reconciliation failed"):
        NormalizationFinalizer(ledger=ledger, object_store=_MemoryStore()).finalize(
            plan=_plan(),
            run_id="run-1",
            scope_id="scope-1",
            pipeline_version="v1",
            config_sha256="c" * 64,
        )
    assert ledger.failed_reason is not None
    assert not ledger.persisted
    assert not ledger.closed
