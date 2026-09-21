from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Json


@dataclass(frozen=True, slots=True)
class RunSummary:
    selected_count: int
    normalized_count: int
    review_required_count: int
    failed_count: int
    skipped_count: int
    pending_count: int
    running_count: int


@dataclass(frozen=True, slots=True)
class RunItemCheckpoint:
    item_id: str
    status: str
    normalized_artifact_id: str | None


@dataclass(frozen=True, slots=True)
class RunItemSnapshot:
    source_artifact_id: str
    status: str
    normalized_artifact_id: str | None
    quality_state: str


@dataclass(frozen=True, slots=True)
class RunReconciliationState:
    run_item_source_ids: frozenset[str]
    referenced_artifact_ids: frozenset[str]
    lineage_artifact_ids: frozenset[str]
    artifact_storage_keys: dict[str, str]
    quality_report_source_ids: frozenset[str]
    items: tuple[RunItemSnapshot, ...]


@dataclass(slots=True)
class PostgresNormalizationLedger:
    connection: psycopg.Connection[Any]

    def resolve_source_artifact_id(self, *, scope_id: str, sha256: str) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select id::text
                from corpus.source_artifacts
                where scope_id=%s and sha256=%s
                """,
                (scope_id, sha256),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"source artifact not registered for sha256={sha256}")
            return str(row[0])

    def create_run(
        self,
        *,
        scope_id: str,
        manifest_locator: str,
        manifest_sha256: str,
        pipeline_version: str,
        config_sha256: str,
        selected_count: int,
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.normalization_runs
                    (scope_id, input_manifest_locator, input_manifest_sha256,
                     pipeline_version, config_sha256, selected_count, status, started_at)
                values (%s, %s, %s, %s, %s, %s, 'running', clock_timestamp())
                returning id::text
                """,
                (
                    scope_id,
                    manifest_locator,
                    manifest_sha256,
                    pipeline_version,
                    config_sha256,
                    selected_count,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            return str(row[0])

    def ensure_item(
        self,
        *,
        scope_id: str,
        run_id: str,
        source_artifact_id: str,
        status: str = "pending",
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.normalization_run_items
                    (scope_id, run_id, source_artifact_id, status)
                values (%s, %s, %s, %s)
                on conflict (scope_id, run_id, source_artifact_id) do nothing
                returning id::text
                """,
                (scope_id, run_id, source_artifact_id, status),
            )
            row = cursor.fetchone()
            if row is not None:
                return str(row[0])
            cursor.execute(
                """
                select id::text
                from corpus.normalization_run_items
                where scope_id=%s and run_id=%s and source_artifact_id=%s
                """,
                (scope_id, run_id, source_artifact_id),
            )
            existing = cursor.fetchone()
            assert existing is not None
            return str(existing[0])

    def find_reusable_artifact(
        self,
        *,
        scope_id: str,
        source_artifact_id: str,
        pipeline_version: str,
        config_sha256: str,
    ) -> str | None:
        """Return only a resolved evidence artifact, never the structural candidate."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select resolved.derived_artifact_id::text
                from corpus.artifact_derivations structural
                join corpus.artifact_derivations resolved
                  on resolved.scope_id=structural.scope_id
                 and resolved.parent_derived_artifact_id=structural.derived_artifact_id
                join corpus.derived_artifacts artifact
                  on artifact.scope_id=resolved.scope_id
                 and artifact.id=resolved.derived_artifact_id
                where structural.scope_id=%s
                  and structural.source_artifact_id=%s
                  and structural.derivation_type='normalize'
                  and structural.pipeline_version=%s
                  and structural.config_sha256=%s
                  and resolved.derivation_type='resolve_evidence_text'
                  and resolved.pipeline_version=%s
                  and resolved.config_sha256=%s
                  and artifact.artifact_kind='resolved-evidence-text'
                order by resolved.created_at desc
                limit 1
                """,
                (
                    scope_id,
                    source_artifact_id,
                    pipeline_version,
                    config_sha256,
                    pipeline_version,
                    config_sha256,
                ),
            )
            row = cursor.fetchone()
            return str(row[0]) if row is not None else None

    def validate_resume_run(
        self,
        *,
        scope_id: str,
        run_id: str,
        manifest_sha256: str,
        pipeline_version: str,
        config_sha256: str,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select status, input_manifest_sha256, pipeline_version, config_sha256
                from corpus.normalization_runs
                where scope_id=%s and id=%s
                """,
                (scope_id, run_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(run_id)
            status = str(row[0])
            if status != 'running':
                raise RuntimeError(
                    f"normalization run {run_id} is not resumable from status {status}"
                )
            expected = (manifest_sha256, pipeline_version, config_sha256)
            actual = (str(row[1]), str(row[2]), str(row[3]))
            if actual != expected:
                raise RuntimeError(
                    "resume request does not match run manifest/pipeline/config identity"
                )

    def item_checkpoint(
        self,
        *,
        scope_id: str,
        run_id: str,
        source_artifact_id: str,
    ) -> RunItemCheckpoint | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select id::text, status, normalized_artifact_id::text
                from corpus.normalization_run_items
                where scope_id=%s and run_id=%s and source_artifact_id=%s
                """,
                (scope_id, run_id, source_artifact_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return RunItemCheckpoint(
                item_id=str(row[0]),
                status=str(row[1]),
                normalized_artifact_id=(
                    str(row[2]) if row[2] is not None else None
                ),
            )

    def register_derived_artifact(
        self,
        *,
        scope_id: str,
        source_artifact_id: str,
        sha256: str,
        artifact_kind: str,
        mime_type: str,
        byte_size: int,
        storage_locator: str,
        engine: str,
        engine_version: str | None,
        pipeline_version: str,
        config_sha256: str,
        parameters: dict[str, object] | None = None,
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.derived_artifacts
                    (scope_id, sha256, artifact_kind, mime_type, byte_size, storage_locator)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (scope_id, sha256, artifact_kind) do nothing
                returning id::text
                """,
                (scope_id, sha256, artifact_kind, mime_type, byte_size, storage_locator),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    select id::text
                    from corpus.derived_artifacts
                    where scope_id=%s and sha256=%s and artifact_kind=%s
                    """,
                    (scope_id, sha256, artifact_kind),
                )
                row = cursor.fetchone()
            assert row is not None
            artifact_id = str(row[0])
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (scope_id, source_artifact_id, derived_artifact_id, derivation_type,
                     engine, engine_version, pipeline_version, config_sha256, parameters)
                values (%s, %s, %s, 'normalize', %s, %s, %s, %s, %s::jsonb)
                on conflict do nothing
                """,
                (
                    scope_id,
                    source_artifact_id,
                    artifact_id,
                    engine,
                    engine_version,
                    pipeline_version,
                    config_sha256,
                    Json(parameters or {}),
                ),
            )
            return artifact_id

    def register_child_derived_artifact(
        self,
        *,
        scope_id: str,
        parent_artifact_id: str,
        sha256: str,
        artifact_kind: str,
        mime_type: str,
        byte_size: int,
        storage_locator: str,
        engine: str,
        engine_version: str | None,
        pipeline_version: str,
        config_sha256: str,
        derivation_type: str,
        parameters: dict[str, object] | None = None,
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.derived_artifacts
                    (scope_id, sha256, artifact_kind, mime_type, byte_size, storage_locator)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (scope_id, sha256, artifact_kind) do nothing
                returning id::text
                """,
                (scope_id, sha256, artifact_kind, mime_type, byte_size, storage_locator),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    select id::text
                    from corpus.derived_artifacts
                    where scope_id=%s and sha256=%s and artifact_kind=%s
                    """,
                    (scope_id, sha256, artifact_kind),
                )
                row = cursor.fetchone()
            assert row is not None
            artifact_id = str(row[0])
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (scope_id, parent_derived_artifact_id, derived_artifact_id,
                     derivation_type, engine, engine_version, pipeline_version,
                     config_sha256, parameters)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict do nothing
                """,
                (
                    scope_id,
                    parent_artifact_id,
                    artifact_id,
                    derivation_type,
                    engine,
                    engine_version,
                    pipeline_version,
                    config_sha256,
                    Json(parameters or {}),
                ),
            )
            return artifact_id

    def record_observation(
        self,
        *,
        scope_id: str,
        run_item_id: str,
        artifact_id: str | None,
        observation_kind: str,
        payload: dict[str, object],
        status: str = "candidate",
        provider: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.normalization_observations
                    (scope_id, run_item_id, artifact_id, observation_kind, payload, status,
                     provider, model, model_version, input_tokens, output_tokens, cost_usd)
                values (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                returning id::text
                """,
                (
                    scope_id,
                    run_item_id,
                    artifact_id,
                    observation_kind,
                    Json(payload),
                    status,
                    provider,
                    model,
                    model_version,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            return str(row[0])

    def record_correction(
        self,
        *,
        scope_id: str,
        observation_id: str,
        verifier_observation_id: str | None,
        replacement_text: str,
        rationale: str | None,
        status: str = "proposed",
    ) -> str:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.normalization_corrections
                    (scope_id, observation_id, verifier_observation_id,
                     replacement_text, rationale, status)
                values (%s, %s, %s, %s, %s, %s)
                returning id::text
                """,
                (
                    scope_id,
                    observation_id,
                    verifier_observation_id,
                    replacement_text,
                    rationale,
                    status,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            return str(row[0])

    def mark_running(self, *, scope_id: str, item_id: str) -> None:
        self._transition(
            scope_id=scope_id,
            item_id=item_id,
            status="running",
            normalized_artifact_id=None,
            error_code=None,
            error_message=None,
        )

    def mark_normalized(
        self, *, scope_id: str, item_id: str, normalized_artifact_id: str
    ) -> None:
        self._transition(
            scope_id=scope_id,
            item_id=item_id,
            status="normalized",
            normalized_artifact_id=normalized_artifact_id,
            error_code=None,
            error_message=None,
        )

    def mark_review_required(
        self, *, scope_id: str, item_id: str, normalized_artifact_id: str
    ) -> None:
        self._transition(
            scope_id=scope_id,
            item_id=item_id,
            status="quality_review_required",
            normalized_artifact_id=normalized_artifact_id,
            error_code=None,
            error_message=None,
        )

    def mark_failed(
        self,
        *,
        scope_id: str,
        item_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        self._transition(
            scope_id=scope_id,
            item_id=item_id,
            status="failed",
            normalized_artifact_id=None,
            error_code=error_code[:200],
            error_message=error_message[:2000],
        )

    def mark_skipped(self, *, scope_id: str, item_id: str) -> None:
        self._transition(
            scope_id=scope_id,
            item_id=item_id,
            status="skipped",
            normalized_artifact_id=None,
            error_code=None,
            error_message=None,
        )

    def _transition(
        self,
        *,
        scope_id: str,
        item_id: str,
        status: str,
        normalized_artifact_id: str | None,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.normalization_run_items
                set status=%s,
                    normalized_artifact_id=coalesce(%s, normalized_artifact_id),
                    error_code=%s,
                    error_message=%s,
                    started_at=case
                        when %s='running' then coalesce(started_at, clock_timestamp())
                        else started_at
                    end,
                    finished_at=case
                        when %s in ('normalized','quality_review_required','failed','skipped')
                            then clock_timestamp()
                        else finished_at
                    end
                where scope_id=%s and id=%s
                """,
                (
                    status,
                    normalized_artifact_id,
                    error_code,
                    error_message,
                    status,
                    status,
                    scope_id,
                    item_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(item_id)

    def summarize_run(self, *, scope_id: str, run_id: str) -> RunSummary:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    count(*)::int,
                    count(*) filter (where status='normalized')::int,
                    count(*) filter (where status='quality_review_required')::int,
                    count(*) filter (where status='failed')::int,
                    count(*) filter (where status='skipped')::int,
                    count(*) filter (where status='pending')::int,
                    count(*) filter (where status='running')::int
                from corpus.normalization_run_items
                where scope_id=%s and run_id=%s
                """,
                (scope_id, run_id),
            )
            row = cursor.fetchone()
            assert row is not None
            return RunSummary(*(int(value) for value in row))

    def reconciliation_state(
        self,
        *,
        scope_id: str,
        run_id: str,
    ) -> RunReconciliationState:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    i.source_artifact_id::text,
                    i.normalized_artifact_id::text,
                    i.status,
                    exists (
                        select 1
                        from corpus.normalization_observations o
                        where o.scope_id=i.scope_id
                          and o.run_item_id=i.id
                          and o.observation_kind in (
                              'deterministic_qa',
                              'reuse_validation'
                          )
                    ) as has_quality
                from corpus.normalization_run_items i
                where i.scope_id=%s and i.run_id=%s
                """,
                (scope_id, run_id),
            )
            rows = cursor.fetchall()

            run_sources = frozenset(str(row[0]) for row in rows)
            referenced = frozenset(
                str(row[1]) for row in rows if row[1] is not None
            )
            quality_sources = frozenset(
                str(row[0]) for row in rows if bool(row[3])
            )
            item_snapshots = tuple(
                RunItemSnapshot(
                    source_artifact_id=str(row[0]),
                    normalized_artifact_id=(
                        str(row[1]) if row[1] is not None else None
                    ),
                    status=str(row[2]),
                    quality_state=(
                        "reported" if bool(row[3]) else "missing"
                    ),
                )
                for row in rows
            )

            if not referenced:
                return RunReconciliationState(
                    run_item_source_ids=run_sources,
                    referenced_artifact_ids=frozenset(),
                    lineage_artifact_ids=frozenset(),
                    artifact_storage_keys={},
                    quality_report_source_ids=quality_sources,
                    items=item_snapshots,
                )

            cursor.execute(
                """
                select d.derived_artifact_id::text
                from corpus.artifact_derivations d
                where d.scope_id=%s
                  and d.derived_artifact_id = any(%s::uuid[])
                """,
                (scope_id, list(referenced)),
            )
            lineage = frozenset(str(row[0]) for row in cursor.fetchall())

            cursor.execute(
                """
                select id::text, storage_locator
                from corpus.derived_artifacts
                where scope_id=%s and id = any(%s::uuid[])
                """,
                (scope_id, list(referenced)),
            )
            storage = {str(row[0]): str(row[1]) for row in cursor.fetchall()}

        return RunReconciliationState(
            run_item_source_ids=run_sources,
            referenced_artifact_ids=referenced,
            lineage_artifact_ids=lineage,
            artifact_storage_keys=storage,
            quality_report_source_ids=quality_sources,
            items=item_snapshots,
        )

    def mark_reconciling(self, *, scope_id: str, run_id: str) -> RunSummary:
        summary = self.summarize_run(scope_id=scope_id, run_id=run_id)
        if summary.pending_count or summary.running_count:
            raise RuntimeError("normalization run still has unfinished items")
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.normalization_runs
                set status='reconciling',
                    normalized_count=%s,
                    review_required_count=%s,
                    failed_count=%s,
                    skipped_count=%s
                where scope_id=%s and id=%s and status='running'
                """,
                (
                    summary.normalized_count,
                    summary.review_required_count,
                    summary.failed_count,
                    summary.skipped_count,
                    scope_id,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("run is not eligible for reconciliation")
        return summary

    def fail_run(
        self,
        *,
        scope_id: str,
        run_id: str,
        reason: str,
    ) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.normalization_runs
                set status='failed',
                    finished_at=clock_timestamp(),
                    metadata=metadata || jsonb_build_object('failure_reason', %s)
                where scope_id=%s and id=%s
                  and status not in ('succeeded','completed_with_errors','cancelled')
                """,
                (reason[:2000], scope_id, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("run cannot transition to failed")

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
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.normalization_manifests
                    (scope_id, run_id, sha256, storage_locator, byte_size,
                     selected_count, normalized_count, review_required_count,
                     failed_count, skipped_count)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id::text
                """,
                (
                    scope_id,
                    run_id,
                    sha256,
                    storage_locator,
                    byte_size,
                    summary.selected_count,
                    summary.normalized_count,
                    summary.review_required_count,
                    summary.failed_count,
                    summary.skipped_count,
                ),
            )
            row = cursor.fetchone()
            assert row is not None
            return str(row[0])

    def close_run(self, *, scope_id: str, run_id: str) -> RunSummary:
        summary = self.summarize_run(scope_id=scope_id, run_id=run_id)
        if summary.pending_count or summary.running_count:
            raise RuntimeError("normalization run still has unfinished items")
        status = (
            "succeeded"
            if summary.failed_count == 0 and summary.review_required_count == 0
            else "completed_with_errors"
        )
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.normalization_runs
                set status=%s,
                    normalized_count=%s,
                    review_required_count=%s,
                    failed_count=%s,
                    skipped_count=%s,
                    finished_at=clock_timestamp()
                where scope_id=%s and id=%s and status='reconciling'
                """,
                (
                    status,
                    summary.normalized_count,
                    summary.review_required_count,
                    summary.failed_count,
                    summary.skipped_count,
                    scope_id,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(run_id)
        return summary
