from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _scalar(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _create_minimal_ingestion_graph(cursor: psycopg.Cursor[Any], *, suffix: str) -> dict[str, Any]:
    cursor.execute(
        """
        insert into corpus.source_registries (code, name, institution, authority_class)
        values (%s, %s, 'Poder Judicial', 'official_primary')
        returning id
        """,
        (f"SCJ-{suffix}", f"SCJ test registry {suffix}"),
    )
    registry_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.source_artifacts (
            source_registry_id, sha256, mime_type, byte_size, page_count
        )
        values (%s, %s, 'application/pdf', 100, 1)
        returning id
        """,
        (registry_id, suffix.lower().zfill(64)[-64:]),
    )
    artifact_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.artifact_pages (
            artifact_id, page_number, extracted_text, extraction_status
        )
        values (%s, 1, 'SCJ-PS-25-0853', 'native_text')
        returning id
        """,
        (artifact_id,),
    )
    artifact_page_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.courts (code, name, jurisdiction)
        values (%s, %s, 'República Dominicana')
        returning id
        """,
        (f"COURT-{suffix}", f"Court {suffix}"),
    )
    court_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.cases (court_id)
        values (%s)
        returning id
        """,
        (court_id,),
    )
    case_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.case_pages (case_id, artifact_page_id, ordinal_in_case)
        values (%s, %s, 1)
        returning id
        """,
        (case_id, artifact_page_id),
    )
    case_page_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.parser_versions (
            parser_name, parser_version, code_revision
        )
        values ('scj_metadata', %s, 'test-revision')
        returning id
        """,
        (suffix,),
    )
    parser_version_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.ingestion_jobs (
            artifact_id, parser_version_id, idempotency_key
        )
        values (%s, %s, %s)
        returning id
        """,
        (artifact_id, parser_version_id, f"job:{suffix}"),
    )
    ingestion_job_id = _scalar(cursor)

    return {
        "artifact_id": artifact_id,
        "case_id": case_id,
        "case_page_id": case_page_id,
        "ingestion_job_id": ingestion_job_id,
    }


def test_observation_can_store_auditable_date_candidate(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _create_minimal_ingestion_graph(cursor, suffix="a1")
        cursor.execute(
            """
            insert into corpus.case_metadata_observations (
                ingestion_job_id,
                case_id,
                observation_key,
                field_name,
                value_type,
                raw_value,
                normalized_date,
                observation_method,
                method_name,
                evidence_case_page_id,
                evidence_excerpt,
                evidence_char_start,
                evidence_char_end
            )
            values (
                %s, %s, repeat('a', 64), 'decision_date_candidate', 'date',
                'en fecha 30 de abril de 2025', date '2025-04-30',
                'deterministic_parser', 'scj_decision_formula_date_v1',
                %s, 'en fecha 30 de abril de 2025', 10, 39
            )
            returning normalized_date, status
            """,
            (
                graph["ingestion_job_id"],
                graph["case_id"],
                graph["case_page_id"],
            ),
        )
        assert cursor.fetchone() == (date(2025, 4, 30), "observed")


def test_observation_cannot_reference_another_cases_page(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first = _create_minimal_ingestion_graph(cursor, suffix="b1")
        second = _create_minimal_ingestion_graph(cursor, suffix="b2")

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_observations (
                    ingestion_job_id,
                    case_id,
                    observation_key,
                    field_name,
                    value_type,
                    raw_value,
                    normalized_text,
                    observation_method,
                    method_name,
                    evidence_case_page_id
                )
                values (
                    %s, %s, repeat('b', 64), 'decision_number', 'identifier',
                    'SCJ-PS-25-0853', 'SCJ-PS-25-0853',
                    'deterministic_parser', 'scj_decision_number_v1', %s
                )
                """,
                (
                    first["ingestion_job_id"],
                    first["case_id"],
                    second["case_page_id"],
                ),
            )
            cursor.execute("set constraints all immediate")


def test_value_type_cannot_use_wrong_normalized_column(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _create_minimal_ingestion_graph(cursor, suffix="c1")

        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_observations (
                    ingestion_job_id,
                    case_id,
                    observation_key,
                    field_name,
                    value_type,
                    raw_value,
                    normalized_text,
                    observation_method,
                    method_name
                )
                values (
                    %s, %s, repeat('c', 64), 'decision_date_candidate', 'date',
                    '30 de abril de 2025', '2025-04-30',
                    'deterministic_parser', 'invalid-test'
                )
                """,
                (graph["ingestion_job_id"], graph["case_id"]),
            )


def test_parser_version_requires_code_revision(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.NotNullViolation):
            cursor.execute(
                """
                insert into corpus.parser_versions (parser_name, parser_version)
                values ('scj_metadata', 'missing-revision-test')
                """
            )


def test_required_ingestion_indexes_exist(connection: psycopg.Connection[Any]) -> None:
    expected = {
        "ingestion_jobs_artifact_idx",
        "ingestion_jobs_parser_version_idx",
        "case_metadata_observations_case_field_idx",
        "case_metadata_observations_date_idx",
        "case_metadata_observations_evidence_page_idx",
        "case_identifiers_same_case_evidence_idx",
        "case_metadata_observations_same_case_evidence_idx",
        "cases_same_case_date_evidence_idx",
    }

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select indexname
            from pg_indexes
            where schemaname = 'corpus'
            """
        )
        indexes = {row[0] for row in cursor.fetchall()}

    assert expected <= indexes
