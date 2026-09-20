from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import errors

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _source_artifact(
    connection: psycopg.Connection[Any],
    *,
    sha_char: str,
) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.source_artifacts (
                sha256, mime_type, byte_size
            ) VALUES (%s, 'application/pdf', 100)
            RETURNING id
            """,
            (sha_char * 64,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def _derived_artifact(
    connection: psycopg.Connection[Any],
    *,
    sha_char: str,
    kind: str,
    suffix: str,
) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.derived_artifacts (
                sha256, artifact_kind, mime_type, byte_size, storage_locator
            ) VALUES (%s, %s, %s, 200, %s)
            RETURNING id
            """,
            (
                sha_char * 64,
                kind,
                "application/json" if suffix == "json" else "application/pdf",
                f"s3://jurisnexo-derived/{sha_char * 64}.{suffix}",
            ),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_source_to_ocr_to_docling_lineage_is_queryable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        source_id = _source_artifact(connection, sha_char="1")
        ocr_id = _derived_artifact(
            connection,
            sha_char="2",
            kind="ocr_pdf",
            suffix="pdf",
        )
        normalized_id = _derived_artifact(
            connection,
            sha_char="3",
            kind="normalized_document",
            suffix="json",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.artifact_derivations (
                    source_artifact_id,
                    derived_artifact_id,
                    derivation_type,
                    engine,
                    engine_version,
                    pipeline_version,
                    config_sha256,
                    parameters
                ) VALUES (%s,%s,'ocr','rapidocr','1','normalize-v1',%s,'{"lang":"es"}')
                """,
                (source_id, ocr_id, "a" * 64),
            )
            cursor.execute(
                """
                INSERT INTO corpus.artifact_derivations (
                    parent_derived_artifact_id,
                    derived_artifact_id,
                    derivation_type,
                    engine,
                    engine_version,
                    pipeline_version,
                    config_sha256,
                    parameters
                ) VALUES (%s,%s,'document_normalization','docling','2','normalize-v1',%s,'{}')
                """,
                (ocr_id, normalized_id, "b" * 64),
            )
            cursor.execute(
                """
                SELECT
                    first.source_artifact_id,
                    first.derived_artifact_id,
                    second.parent_derived_artifact_id,
                    second.derived_artifact_id
                FROM corpus.artifact_derivations first
                JOIN corpus.artifact_derivations second
                  ON second.parent_derived_artifact_id = first.derived_artifact_id
                WHERE first.source_artifact_id = %s
                """,
                (source_id,),
            )
            row = cursor.fetchone()

        assert row == (source_id, ocr_id, ocr_id, normalized_id)


def test_derivation_requires_exactly_one_parent(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        source_id = _source_artifact(connection, sha_char="4")
        parent_id = _derived_artifact(
            connection,
            sha_char="5",
            kind="ocr_pdf",
            suffix="pdf",
        )
        child_id = _derived_artifact(
            connection,
            sha_char="6",
            kind="normalized_document",
            suffix="json",
        )

        with pytest.raises(errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO corpus.artifact_derivations (
                            source_artifact_id,
                            parent_derived_artifact_id,
                            derived_artifact_id,
                            derivation_type,
                            engine,
                            pipeline_version,
                            config_sha256
                        ) VALUES (%s,%s,%s,'invalid','fixture','v1',%s)
                        """,
                        (source_id, parent_id, child_id, "c" * 64),
                    )


def test_derived_artifact_lineage_rejects_cycles(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        source_id = _source_artifact(connection, sha_char="7")
        first_id = _derived_artifact(
            connection,
            sha_char="8",
            kind="ocr_pdf",
            suffix="pdf",
        )
        second_id = _derived_artifact(
            connection,
            sha_char="9",
            kind="normalized_document",
            suffix="json",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.artifact_derivations (
                    source_artifact_id, derived_artifact_id, derivation_type,
                    engine, pipeline_version, config_sha256
                ) VALUES (%s,%s,'ocr','fixture','v1',%s)
                """,
                (source_id, first_id, "d" * 64),
            )
            cursor.execute(
                """
                INSERT INTO corpus.artifact_derivations (
                    parent_derived_artifact_id, derived_artifact_id,
                    derivation_type, engine, pipeline_version, config_sha256
                ) VALUES (%s,%s,'normalize','fixture','v1',%s)
                """,
                (first_id, second_id, "e" * 64),
            )

        with pytest.raises(errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO corpus.artifact_derivations (
                            parent_derived_artifact_id, derived_artifact_id,
                            derivation_type, engine, pipeline_version, config_sha256
                        ) VALUES (%s,%s,'cycle','fixture','v1',%s)
                        """,
                        (second_id, first_id, "f" * 64),
                    )


def test_normalization_run_is_manifest_scoped_and_tracks_outputs(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        source_id = _source_artifact(connection, sha_char="a")
        normalized_id = _derived_artifact(
            connection,
            sha_char="b",
            kind="normalized_document",
            suffix="json",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.normalization_runs (
                    input_manifest_locator,
                    input_manifest_sha256,
                    pipeline_version,
                    config_sha256,
                    status,
                    selected_count
                ) VALUES (
                    's3://jurisnexo/_manifests/scj/example.json',
                    %s,
                    'jurisnexo-normalization-v1',
                    %s,
                    'running',
                    1
                )
                RETURNING id
                """,
                ("1" * 64, "2" * 64),
            )
            run_row = cursor.fetchone()
            assert run_row is not None
            run_id = run_row[0]

            cursor.execute(
                """
                INSERT INTO corpus.normalization_run_items (
                    run_id,
                    source_artifact_id,
                    status,
                    normalized_artifact_id,
                    quality_summary,
                    started_at,
                    finished_at
                ) VALUES (
                    %s,%s,'normalized',%s,
                    '{"docling":{"status":"ok"}}',
                    clock_timestamp(),
                    clock_timestamp()
                )
                """,
                (run_id, source_id, normalized_id),
            )
            cursor.execute(
                """
                SELECT r.input_manifest_sha256,
                       r.pipeline_version,
                       i.status,
                       i.normalized_artifact_id
                FROM corpus.normalization_runs r
                JOIN corpus.normalization_run_items i ON i.run_id = r.id
                WHERE r.id = %s
                """,
                (run_id,),
            )
            row = cursor.fetchone()

        assert row == (
            "1" * 64,
            "jurisnexo-normalization-v1",
            "normalized",
            normalized_id,
        )
