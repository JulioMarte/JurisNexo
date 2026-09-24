from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from jurisnexo.normalization.repository import PostgresNormalizationLedger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_reuse_returns_resolved_evidence_not_structural_candidate(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("a" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.derived_artifacts
                (sha256, artifact_kind, mime_type, byte_size, storage_locator)
            values
                (%s, 'docling-json', 'application/json', 10, 's3://d/structural'),
                (%s, 'resolved-evidence-text', 'text/plain', 5, 's3://d/resolved')
            returning id::text
            """,
            ("b" * 64, "c" * 64),
        )
        structural = cursor.fetchone()
        resolved = cursor.fetchone()
        assert structural is not None
        assert resolved is not None

        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values (%s, %s, 'normalize', 'docling', 'v1', %s)
            """,
            (source[0], structural[0], "d" * 64),
        )
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (parent_derived_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values (
                %s, %s, 'resolve_evidence_text',
                'jurisnexo-resolver', 'v1', %s
            )
            """,
            (structural[0], resolved[0], "d" * 64),
        )

        ledger = PostgresNormalizationLedger(connection)
        reusable = ledger.find_reusable_artifact(
            scope_id="00000000-0000-0000-0000-000000000001",
            source_artifact_id=str(source[0]),
            pipeline_version="v1",
            config_sha256="d" * 64,
        )
        assert reusable == str(resolved[0])
        assert reusable != str(structural[0])


def test_resume_identity_and_checkpoint_are_durable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("e" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                's3://manifest/resume.json',
                %s, 'v1', %s, 1, 'running', clock_timestamp()
            )
            returning id::text
            """,
            ("f" * 64, "1" * 64),
        )
        run = cursor.fetchone()
        assert run is not None

        cursor.execute(
            """
            insert into corpus.normalization_run_items
                (run_id, source_artifact_id, status, started_at)
            values (%s, %s, 'running', clock_timestamp())
            returning id::text
            """,
            (run[0], source[0]),
        )
        item = cursor.fetchone()
        assert item is not None

        ledger = PostgresNormalizationLedger(connection)
        ledger.validate_resume_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            manifest_sha256="f" * 64,
            pipeline_version="v1",
            config_sha256="1" * 64,
        )
        checkpoint = ledger.item_checkpoint(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        assert checkpoint is not None
        assert checkpoint.item_id == str(item[0])
        assert checkpoint.status == "running"
        assert checkpoint.normalized_artifact_id is None

        with pytest.raises(RuntimeError, match="does not match"):
            ledger.validate_resume_run(
                scope_id="00000000-0000-0000-0000-000000000001",
                run_id=str(run[0]),
                manifest_sha256="0" * 64,
                pipeline_version="v1",
                config_sha256="1" * 64,
            )


def test_retryable_item_returns_to_pending_for_same_run_resume(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("2" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                's3://manifest/retryable.json',
                %s, 'v1', %s, 1, 'running', clock_timestamp()
            )
            returning id::text
            """,
            ("3" * 64, "4" * 64),
        )
        run = cursor.fetchone()
        assert run is not None

        ledger = PostgresNormalizationLedger(connection)
        item_id = ledger.ensure_item(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        ledger.mark_running(
            scope_id="00000000-0000-0000-0000-000000000001",
            item_id=item_id,
        )
        ledger.mark_retryable(
            scope_id="00000000-0000-0000-0000-000000000001",
            item_id=item_id,
            error_code="TimeoutError",
            error_message="temporary upstream timeout",
        )

        checkpoint = ledger.item_checkpoint(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        assert checkpoint is not None
        assert checkpoint.status == "pending"
        summary = ledger.summarize_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
        )
        assert summary.pending_count == 1
        assert summary.failed_count == 0

        ledger.validate_resume_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            manifest_sha256="3" * 64,
            pipeline_version="v1",
            config_sha256="4" * 64,
        )
