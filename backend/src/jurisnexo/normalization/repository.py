from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg


@dataclass(frozen=True, slots=True)
class RunSummary:
    selected_count: int
    normalized_count: int
    review_required_count: int
    failed_count: int
    skipped_count: int
    pending_count: int
    running_count: int


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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select d.derived_artifact_id::text
                from corpus.artifact_derivations d
                where d.scope_id=%s
                  and d.source_artifact_id=%s
                  and d.derivation_type='normalize'
                  and d.pipeline_version=%s
                  and d.config_sha256=%s
                order by d.created_at desc
                limit 1
                """,
                (scope_id, source_artifact_id, pipeline_version, config_sha256),
            )
            row = cursor.fetchone()
            return str(row[0]) if row is not None else None

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
                    psycopg.types.json.Json(parameters or {}),
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
                    psycopg.types.json.Json(parameters or {}),
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
                    psycopg.types.json.Json(payload),
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
