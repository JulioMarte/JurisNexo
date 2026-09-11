from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from jurisnexo.ingestion.observation_persistence import (
    ObservationPersistenceContext,
    persist_metadata_observations,
)
from jurisnexo.ingestion.scj_metadata import parse_scj_page_metadata

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


SAMPLE_PAGE = """\
SCJ-PS-25-0853
Expediente núm. 001-022-2024-RECA-00421
Materia: Civil
La Primera Sala, en fecha 30 de abril de 2025, dicta la siguiente sentencia.
"""


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _uuid(cursor: psycopg.Cursor[Any]) -> UUID:
    row = cursor.fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, UUID)
    return value


def _create_context(
    cursor: psycopg.Cursor[Any],
    *,
    suffix: str,
) -> ObservationPersistenceContext:
    cursor.execute(
        """
        INSERT INTO corpus.source_registries (code, name, institution, authority_class)
        VALUES (%s, %s, 'Poder Judicial', 'official_primary')
        RETURNING id
        """,
        (f"PERSIST-{suffix}", f"Persistence test registry {suffix}"),
    )
    registry_id = _uuid(cursor)

    sha256 = (suffix * 64)[:64].lower()
    cursor.execute(
        """
        INSERT INTO corpus.source_artifacts (
            source_registry_id, sha256, mime_type, byte_size, page_count
        )
        VALUES (%s, %s, 'application/pdf', 100, 1)
        RETURNING id
        """,
        (registry_id, sha256),
    )
    artifact_id = _uuid(cursor)

    cursor.execute(
        """
        INSERT INTO corpus.artifact_pages (
            artifact_id, page_number, extracted_text, extraction_status
        )
        VALUES (%s, 1, %s, 'native_text')
        RETURNING id
        """,
        (artifact_id, SAMPLE_PAGE),
    )
    artifact_page_id = _uuid(cursor)

    cursor.execute(
        """
        INSERT INTO corpus.courts (code, name, jurisdiction)
        VALUES (%s, %s, 'República Dominicana')
        RETURNING id
        """,
        (f"COURT-PERSIST-{suffix}", f"Persistence court {suffix}"),
    )
    court_id = _uuid(cursor)

    cursor.execute(
        "INSERT INTO corpus.cases (court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    case_id = _uuid(cursor)

    cursor.execute(
        """
        INSERT INTO corpus.case_pages (
            case_id, artifact_id, artifact_page_id, ordinal_in_case
        )
        VALUES (%s, %s, %s, 1)
        RETURNING id
        """,
        (case_id, artifact_id, artifact_page_id),
    )
    case_page_id = _uuid(cursor)

    cursor.execute(
        """
        INSERT INTO corpus.parser_versions (
            parser_name, parser_version, code_revision
        )
        VALUES ('scj_metadata', %s, 'test-revision')
        RETURNING id
        """,
        (f"persist-{suffix}",),
    )
    parser_version_id = _uuid(cursor)

    cursor.execute(
        """
        INSERT INTO corpus.ingestion_jobs (
            artifact_id, parser_version_id, idempotency_key
        )
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (artifact_id, parser_version_id, f"persist-job:{suffix}"),
    )
    ingestion_job_id = _uuid(cursor)

    return ObservationPersistenceContext(
        ingestion_job_id=ingestion_job_id,
        artifact_id=artifact_id,
        case_id=case_id,
        case_page_ids_by_page_number={1: case_page_id},
    )


def test_persists_typed_observations_with_evidence_offsets(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        context = _create_context(cursor, suffix="a")
        observations = parse_scj_page_metadata(SAMPLE_PAGE, page_number=1)

        inserted = persist_metadata_observations(
            connection,
            context=context,
            observations=observations,
        )

        assert inserted == len(observations)
        cursor.execute(
            """
            SELECT field_name, normalized_text, normalized_date,
                   evidence_excerpt, evidence_char_start, evidence_char_end,
                   artifact_id, case_id, ingestion_job_id
            FROM corpus.case_metadata_observations
            WHERE ingestion_job_id = %s
            ORDER BY field_name
            """,
            (context.ingestion_job_id,),
        )
        rows = cursor.fetchall()

        assert len(rows) == len(observations)
        assert any(
            row[0] == "decision_date_candidate"
            and row[1] is None
            and str(row[2]) == "2025-04-30"
            for row in rows
        )
        assert all(row[3] and row[4] >= 0 and row[5] > row[4] for row in rows)
        assert all(row[6] == context.artifact_id for row in rows)
        assert all(row[7] == context.case_id for row in rows)
        assert all(row[8] == context.ingestion_job_id for row in rows)


def test_repeated_persistence_is_idempotent(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        context = _create_context(cursor, suffix="b")
        observations = parse_scj_page_metadata(SAMPLE_PAGE, page_number=1)

        first = persist_metadata_observations(
            connection,
            context=context,
            observations=observations,
        )
        second = persist_metadata_observations(
            connection,
            context=context,
            observations=observations,
        )

        assert first == len(observations)
        assert second == 0
        cursor.execute(
            """
            SELECT count(*)
            FROM corpus.case_metadata_observations
            WHERE ingestion_job_id = %s
            """,
            (context.ingestion_job_id,),
        )
        assert cursor.fetchone() == (len(observations),)


def test_missing_case_page_mapping_fails_before_insert(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        context = _create_context(cursor, suffix="c")
        bad_context = ObservationPersistenceContext(
            ingestion_job_id=context.ingestion_job_id,
            artifact_id=context.artifact_id,
            case_id=context.case_id,
            case_page_ids_by_page_number={},
        )
        observations = parse_scj_page_metadata(SAMPLE_PAGE, page_number=1)

        with pytest.raises(KeyError, match="No case_page_id mapping"):
            persist_metadata_observations(
                connection,
                context=bad_context,
                observations=observations,
            )

        cursor.execute(
            """
            SELECT count(*)
            FROM corpus.case_metadata_observations
            WHERE ingestion_job_id = %s
            """,
            (context.ingestion_job_id,),
        )
        assert cursor.fetchone() == (0,)


def test_database_rejects_context_artifact_mismatch(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        context_a = _create_context(cursor, suffix="d")
        context_b = _create_context(cursor, suffix="e")
        mismatched = ObservationPersistenceContext(
            ingestion_job_id=context_a.ingestion_job_id,
            artifact_id=context_b.artifact_id,
            case_id=context_a.case_id,
            case_page_ids_by_page_number=context_a.case_page_ids_by_page_number,
        )
        observations = parse_scj_page_metadata(SAMPLE_PAGE, page_number=1)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            persist_metadata_observations(
                connection,
                context=mismatched,
                observations=observations,
            )
