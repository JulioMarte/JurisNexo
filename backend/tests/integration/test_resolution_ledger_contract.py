from __future__ import annotations

import os
from collections.abc import Iterator
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


def _graph(cursor: psycopg.Cursor[Any], suffix: str) -> dict[str, Any]:
    cursor.execute(
        """
        insert into corpus.source_registries (code, name, institution, authority_class)
        values (%s, %s, 'Poder Judicial', 'official_primary')
        returning id
        """,
        (f"RES-{suffix}", f"Resolution registry {suffix}"),
    )
    registry_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.source_artifacts (
            source_registry_id, sha256, mime_type, byte_size, page_count
        ) values (%s, %s, 'application/pdf', 100, 1)
        returning id
        """,
        (registry_id, suffix.lower().zfill(64)[-64:]),
    )
    artifact_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.artifact_pages (
            artifact_id, page_number, extracted_text, extraction_status
        ) values (%s, 1, 'dicta la siguiente sentencia', 'native_text')
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
        (f"RES-COURT-{suffix}", f"Resolution court {suffix}"),
    )
    court_id = _scalar(cursor)
    cursor.execute("insert into corpus.cases (court_id) values (%s) returning id", (court_id,))
    case_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.case_pages (case_id, artifact_id, artifact_page_id, ordinal_in_case)
        values (%s, %s, %s, 1)
        returning id
        """,
        (case_id, artifact_id, artifact_page_id),
    )
    case_page_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.parser_versions (parser_name, parser_version, code_revision)
        values ('resolution-test', %s, 'test-revision')
        returning id
        """,
        (suffix,),
    )
    parser_version_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.ingestion_jobs (artifact_id, parser_version_id, idempotency_key)
        values (%s, %s, %s)
        returning id
        """,
        (artifact_id, parser_version_id, f"resolution-job:{suffix}"),
    )
    ingestion_job_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.case_metadata_observations (
            ingestion_job_id, artifact_id, case_id, observation_key,
            field_name, value_type, raw_value, normalized_date,
            observation_method, method_name, evidence_case_page_id
        ) values (
            %s, %s, %s, %s, 'decision_date', 'date',
            '30 de abril de 2025', date '2025-04-30',
            'deterministic_parser', 'resolution_test_v1', %s
        ) returning id
        """,
        (
            ingestion_job_id,
            artifact_id,
            case_id,
            (suffix.lower() * 64)[:64],
            case_page_id,
        ),
    )
    observation_id = _scalar(cursor)
    return {"case_id": case_id, "observation_id": observation_id}


def _resolution(cursor: psycopg.Cursor[Any], graph: dict[str, Any], suffix: str) -> Any:
    cursor.execute(
        """
        insert into corpus.case_metadata_resolutions (
            case_id, field_name, value_type, resolved_date, resolution_status,
            resolver_name, resolver_version, code_revision, idempotency_key
        ) values (
            %s, 'decision_date', 'date', date '2025-04-30', 'parsed_high_confidence',
            'decision_date_reconciler', '1', 'test-revision', %s
        ) returning id
        """,
        (graph["case_id"], ("f" + suffix.lower()).ljust(64, "0")[:64]),
    )
    return _scalar(cursor)


def test_resolution_tables_and_composite_indexes_exist(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select table_name from information_schema.tables
            where table_schema = 'corpus'
              and table_name in (
                  'case_metadata_resolutions',
                  'case_metadata_resolution_observations'
              )
            """
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "case_metadata_resolutions",
            "case_metadata_resolution_observations",
        }
        cursor.execute("select indexname from pg_indexes where schemaname = 'corpus'")
        indexes = {row[0] for row in cursor.fetchall()}
        assert "case_metadata_resolution_observations_case_resolution_idx" in indexes
        assert "case_metadata_resolution_observations_case_observation_idx" in indexes


def test_conflicting_resolution_cannot_carry_a_canonical_value(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _graph(cursor, "a")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_resolutions (
                    case_id, field_name, value_type, resolved_date, resolution_status,
                    resolver_name, resolver_version, code_revision, idempotency_key
                ) values (
                    %s, 'decision_date', 'date', date '2025-04-30', 'conflicting',
                    'decision_date_reconciler', '1', 'test-revision', repeat('a', 64)
                )
                """,
                (graph["case_id"],),
            )


def test_eligible_resolution_requires_exactly_one_typed_value(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _graph(cursor, "b")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_resolutions (
                    case_id, field_name, value_type, resolution_status,
                    resolver_name, resolver_version, code_revision, idempotency_key
                ) values (
                    %s, 'decision_date', 'date', 'parsed_high_confidence',
                    'decision_date_reconciler', '1', 'test-revision', repeat('b', 64)
                )
                """,
                (graph["case_id"],),
            )


def test_resolution_cannot_link_an_observation_from_another_case(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first = _graph(cursor, "c")
        second = _graph(cursor, "d")
        resolution_id = _resolution(cursor, first, "c")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_resolution_observations (
                    resolution_id, case_id, observation_id, role
                ) values (%s, %s, %s, 'supporting')
                """,
                (resolution_id, first["case_id"], second["observation_id"]),
            )


def test_resolution_allows_only_one_selected_observation(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _graph(cursor, "e")
        resolution_id = _resolution(cursor, graph, "e")
        cursor.execute(
            """
            insert into corpus.case_metadata_resolution_observations (
                resolution_id, case_id, observation_id, role
            ) values (%s, %s, %s, 'selected')
            """,
            (resolution_id, graph["case_id"], graph["observation_id"]),
        )

        cursor.execute(
            """
            insert into corpus.case_metadata_observations (
                ingestion_job_id, artifact_id, case_id, observation_key,
                field_name, value_type, raw_value, normalized_date,
                observation_method, method_name, evidence_case_page_id
            )
            select ingestion_job_id, artifact_id, case_id, repeat('9', 64),
                   field_name, value_type, raw_value, normalized_date,
                   observation_method, method_name, evidence_case_page_id
            from corpus.case_metadata_observations
            where id = %s
            returning id
            """,
            (graph["observation_id"],),
        )
        second_observation_id = _scalar(cursor)
        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                insert into corpus.case_metadata_resolution_observations (
                    resolution_id, case_id, observation_id, role
                ) values (%s, %s, %s, 'selected')
                """,
                (resolution_id, graph["case_id"], second_observation_id),
            )
