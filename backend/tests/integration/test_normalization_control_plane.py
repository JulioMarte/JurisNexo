from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

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


def _scope(cursor: psycopg.Cursor[Any]) -> Any:
    cursor.execute(
        """
        insert into corpus.scopes (visibility, organization_id)
        values ('private', gen_random_uuid())
        returning id
        """
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _source(cursor: psycopg.Cursor[Any], char: str, *, scope_id: Any | None = None) -> Any:
    cursor.execute(
        """
        insert into corpus.source_artifacts (scope_id, sha256, mime_type, byte_size)
        values (coalesce(%s, '00000000-0000-0000-0000-000000000001'::uuid),
                %s, 'application/pdf', 1)
        returning id
        """,
        (scope_id, char * 64),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _derived(cursor: psycopg.Cursor[Any], char: str, *, scope_id: Any | None = None) -> Any:
    cursor.execute(
        """
        insert into corpus.derived_artifacts
            (scope_id, sha256, artifact_kind, mime_type, byte_size, storage_locator)
        values (coalesce(%s, '00000000-0000-0000-0000-000000000001'::uuid),
                %s, 'docling_json', 'application/json', 2, %s)
        returning id
        """,
        (scope_id, char * 64, f"s3://derived/{char * 64}.json"),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _run(
    cursor: psycopg.Cursor[Any],
    char: str,
    *,
    scope_id: Any | None = None,
) -> Any:
    cursor.execute(
        """
        insert into corpus.normalization_runs
            (scope_id, input_manifest_locator, input_manifest_sha256,
             pipeline_version, config_sha256)
        values (coalesce(%s, '00000000-0000-0000-0000-000000000001'::uuid),
                %s, %s, 'v1', %s)
        returning id
        """,
        (scope_id, f"s3://manifests/{char}.json", char * 64, char * 64),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _run_item(
    cursor: psycopg.Cursor[Any],
    *,
    run_id: Any,
    source_artifact_id: Any,
    scope_id: Any | None = None,
) -> Any:
    cursor.execute(
        """
        insert into corpus.normalization_run_items
            (scope_id, run_id, source_artifact_id)
        values (coalesce(%s, '00000000-0000-0000-0000-000000000001'::uuid), %s, %s)
        returning id
        """,
        (scope_id, run_id, source_artifact_id),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_lineage_requires_exactly_one_parent_kind(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "a")
        derived = _derived(cursor, "b")
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (derived_artifact_id, derivation_type, engine,
                     pipeline_version, config_sha256)
                values (%s, 'normalize', 'fixture', 'v1', %s)
                """,
                (derived, "c" * 64),
            )
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.CheckViolation),
        ):
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
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (parent_derived_artifact_id, derived_artifact_id, derivation_type, engine,
                     pipeline_version, config_sha256)
                values (%s, %s, 'transform', 'fixture', 'v1', %s)
                """,
                (third, first, "4" * 64),
            )


def test_lineage_cannot_cross_scope(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        other_scope = _scope(cursor)
        source = _source(cursor, "5")
        derived = _derived(cursor, "6", scope_id=other_scope)
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.ForeignKeyViolation),
        ):
            cursor.execute(
                """
                insert into corpus.artifact_derivations
                    (scope_id, source_artifact_id, derived_artifact_id,
                     derivation_type, engine, pipeline_version, config_sha256)
                values (%s, %s, %s, 'normalize', 'fixture', 'v1', %s)
                """,
                (other_scope, source, derived, "7" * 64),
            )


def test_derived_artifacts_and_lineage_are_immutable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "8")
        derived = _derived(cursor, "9")
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type, engine,
                 pipeline_version, config_sha256)
            values (%s, %s, 'normalize', 'fixture', 'v1', %s)
            returning id
            """,
            (source, derived, "a" * 64),
        )
        derivation = cursor.fetchone()
        assert derivation is not None

        for statement, value in (
            (
                sql.SQL(
                    "update corpus.derived_artifacts "
                    "set mime_type='text/plain' where id=%s"
                ),
                derived,
            ),
            (
                sql.SQL(
                    "delete from corpus.artifact_derivations where id=%s"
                ),
                derivation[0],
            ),
        ):
            with (
                connection.transaction(force_rollback=True),
                pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            ):
                cursor.execute(statement, (value,))


def test_run_item_is_idempotent_per_source(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "b")
        run = _run(cursor, "c")
        _run_item(cursor, run_id=run, source_artifact_id=source)
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.UniqueViolation),
        ):
            _run_item(cursor, run_id=run, source_artifact_id=source)


def test_normalized_item_requires_output_artifact(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "d")
        run = _run(cursor, "e")
        with (
            connection.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            cursor.execute(
                """
                insert into corpus.normalization_run_items
                    (run_id, source_artifact_id, status)
                values (%s, %s, 'normalized')
                """,
                (run, source),
            )


def test_observations_corrections_and_manifest_are_append_only(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source = _source(cursor, "f")
        run = _run(cursor, "1")
        item = _run_item(cursor, run_id=run, source_artifact_id=source)
        artifact = _derived(cursor, "2")
        cursor.execute(
            """
            insert into corpus.normalization_observations
                (run_item_id, artifact_id, observation_kind, payload, status)
            values (%s, %s, 'ocr_text', '{"text":"texto"}'::jsonb, 'accepted')
            returning id
            """,
            (item, artifact),
        )
        observation = cursor.fetchone()
        assert observation is not None
        cursor.execute(
            """
            insert into corpus.normalization_corrections
                (observation_id, replacement_text, status)
            values (%s, 'texto corregido', 'accepted')
            returning id
            """,
            (observation[0],),
        )
        correction = cursor.fetchone()
        assert correction is not None

        cursor.execute(
            """
            insert into corpus.normalization_manifests
                (run_id, sha256, storage_locator, byte_size, selected_count,
                 normalized_count, review_required_count, failed_count, skipped_count)
            values (%s, %s, 's3://manifests/normalization/run.json', 123, 1, 1, 0, 0, 0)
            returning id
            """,
            (run, "4" * 64),
        )
        manifest = cursor.fetchone()
        assert manifest is not None

        for table, identifier in (
            ("normalization_observations", observation[0]),
            ("normalization_corrections", correction[0]),
            ("normalization_manifests", manifest[0]),
        ):
            with (
                connection.transaction(force_rollback=True),
                pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            ):
                cursor.execute(
                    sql.SQL("delete from corpus.{} where id=%s").format(
                        sql.Identifier(table)
                    ),
                    (identifier,),
                )



@pytest.mark.adversarial
def test_concurrent_opposite_lineage_edges_cannot_create_cycle(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        source = _source(cursor, "5")
        first = _derived(cursor, "6")
        second = _derived(cursor, "7")
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values
                (%s, %s, 'normalize', 'fixture', 'v1', %s),
                (%s, %s, 'normalize', 'fixture', 'v1', %s)
            """,
            (source, first, "8" * 64, source, second, "8" * 64),
        )

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def insert_edge(parent: Any, child: Any) -> None:
        outcome: str
        try:
            with psycopg.connect(
                os.environ["DATABASE_URL"],
                autocommit=True,
            ) as concurrent, concurrent.cursor() as cursor:
                barrier.wait(timeout=10)
                cursor.execute(
                        """
                        insert into corpus.artifact_derivations
                            (parent_derived_artifact_id, derived_artifact_id,
                             derivation_type, engine, pipeline_version,
                             config_sha256)
                        values (%s, %s, 'transform', 'fixture', 'v1', %s)
                        """,
                        (parent, child, "9" * 64),
                    )
            outcome = "committed"
        except psycopg.errors.CheckViolation:
            outcome = "rejected"
        with lock:
            outcomes.append(outcome)

    first_thread = threading.Thread(target=insert_edge, args=(first, second))
    second_thread = threading.Thread(target=insert_edge, args=(second, first))
    first_thread.start()
    second_thread.start()
    first_thread.join(timeout=20)
    second_thread.join(timeout=20)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert sorted(outcomes) == ["committed", "rejected"]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select count(*)
            from corpus.artifact_derivation_paths
            where ancestor_artifact_id in (%s, %s)
              and descendant_artifact_id in (%s, %s)
            """,
            (first, second, first, second),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 1
