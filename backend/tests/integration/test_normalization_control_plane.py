from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

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


def _source(cursor: psycopg.Cursor[Any], char: str) -> Any:
    cursor.execute(
        """
        insert into corpus.source_artifacts (sha256, mime_type, byte_size)
        values (%s, 'application/pdf', 1)
        returning id
        """,
        (char * 64,),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _derived(cursor: psycopg.Cursor[Any], char: str) -> Any:
    cursor.execute(
        """
        insert into corpus.derived_artifacts
            (sha256, artifact_kind, mime_type, byte_size, storage_locator)
        values (%s, 'docling_json', 'application/json', 2, %s)
        returning id
        """,
        (char * 64, f"s3://derived/{char * 64}.json"),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_lineage_requires_exactly_one_parent_kind(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "a")
        derived = _derived(cursor, "b")
        with connection.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (derived_artifact_id, derivation_type, engine, pipeline_version, config_sha256)
                values (%s, 'normalize', 'fixture', 'v1', %s)
                """,
                (derived, "c" * 64),
            )
        with connection.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (source_artifact_id, parent_derived_artifact_id, derived_artifact_id,
                     derivation_type, engine, pipeline_version, config_sha256)
                values (%s, %s, %s, 'normalize', 'fixture', 'v1', %s)
                """,
                (source, derived, derived, "c" * 64),
            )


def test_lineage_rejects_transitive_cycle(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "d")
        first = _derived(cursor, "e")
        second = _derived(cursor, "f")
        third = _derived(cursor, "1")
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type, engine,
                 pipeline_version, config_sha256)
            values (%s, %s, 'normalize', 'fixture', 'v1', %s)
            """,
            (source, first, "2" * 64),
        )
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (parent_derived_artifact_id, derived_artifact_id, derivation_type, engine,
                 pipeline_version, config_sha256)
            values (%s, %s, 'transform', 'fixture', 'v1', %s),
                   (%s, %s, 'transform', 'fixture', 'v1', %s)
            """,
            (first, second, "3" * 64, second, third, "3" * 64),
        )
        with connection.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (parent_derived_artifact_id, derived_artifact_id, derivation_type, engine,
                     pipeline_version, config_sha256)
                values (%s, %s, 'transform', 'fixture', 'v1', %s)
                """,
                (third, first, "4" * 64),
            )


def test_run_is_manifest_scoped_and_item_is_idempotent_per_source(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "5")
        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256, pipeline_version, config_sha256,
                 selected_count)
            values ('s3://manifests/run.json', %s, 'v1', %s, 1)
            returning id
            """,
            ("6" * 64, "7" * 64),
        )
        run = cursor.fetchone()
        assert run is not None
        cursor.execute(
            """
            insert into corpus.normalization_run_items (run_id, source_artifact_id)
            values (%s, %s)
            """,
            (run[0], source),
        )
        with connection.transaction(force_rollback=True), pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                insert into corpus.normalization_run_items (run_id, source_artifact_id)
                values (%s, %s)
                """,
                (run[0], source),
            )


def test_normalized_item_requires_output_artifact(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "8")
        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256, pipeline_version, config_sha256)
            values ('s3://manifests/run2.json', %s, 'v1', %s)
            returning id
            """,
            ("9" * 64, "a" * 64),
        )
        run = cursor.fetchone()
        assert run is not None
        with connection.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.normalization_run_items (run_id, source_artifact_id, status)
                values (%s, %s, 'normalized')
                """,
                (run[0], source),
            )
