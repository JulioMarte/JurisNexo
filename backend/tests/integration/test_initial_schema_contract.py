from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="module")
def connection() -> psycopg.Connection[tuple[object, ...]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as conn:
        yield conn


def test_expected_corpus_tables_exist(connection: psycopg.Connection[tuple[object, ...]]) -> None:
    expected = {
        "source_registries",
        "source_artifacts",
        "source_artifact_locations",
        "artifact_pages",
        "courts",
        "court_organs",
        "cases",
        "case_identifiers",
        "case_artifact_occurrences",
        "case_pages",
        "passages",
    }

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'corpus'
            """
        )
        actual = {row[0] for row in cursor.fetchall()}

    assert expected <= actual


def test_decision_date_is_a_real_date_with_provenance_status(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select data_type
            from information_schema.columns
            where table_schema = 'corpus'
              and table_name = 'cases'
              and column_name = 'decision_date'
            """
        )
        assert cursor.fetchone() == ("date",)

        cursor.execute(
            """
            select is_nullable
            from information_schema.columns
            where table_schema = 'corpus'
              and table_name = 'cases'
              and column_name = 'decision_date_status'
            """
        )
        assert cursor.fetchone() == ("NO",)


def test_verified_decision_date_cannot_be_null(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    with connection.transaction(force_rollback=True):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.courts (code, name, jurisdiction)
                values ('SCJ-CONTRACT', 'Suprema Corte de Justicia - contract test', 'República Dominicana')
                returning id
                """
            )
            court_id = cursor.fetchone()[0]

            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    """
                    insert into corpus.cases (court_id, decision_date_status)
                    values (%s, 'verified_primary_text')
                    """,
                    (court_id,),
                )


def test_spanish_fts_matches_legal_phrase(
    connection: psycopg.Connection[tuple[object, ...]],
) -> None:
    with connection.transaction(force_rollback=True):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.courts (code, name, jurisdiction)
                values ('SCJ-FTS', 'Suprema Corte de Justicia - FTS test', 'República Dominicana')
                returning id
                """
            )
            court_id = cursor.fetchone()[0]
            cursor.execute(
                """
                insert into corpus.cases (
                    court_id,
                    decision_number,
                    decision_date,
                    decision_date_status
                )
                values (%s, 'SCJ-TEST-25-00001', date '2025-01-15', 'parsed_high_confidence')
                returning id
                """,
                (court_id,),
            )
            case_id = cursor.fetchone()[0]
            cursor.execute(
                """
                insert into corpus.passages (
                    case_id, page_start, page_end, passage_order, text
                )
                values (%s, 1, 1, 1, 'La sentencia analiza la responsabilidad civil y el recurso de casación.')
                """,
                (case_id,),
            )
            cursor.execute(
                """
                select exists (
                    select 1
                    from corpus.passages
                    where case_id = %s
                      and fts @@ websearch_to_tsquery('spanish', 'responsabilidad civil')
                )
                """,
                (case_id,),
            )
            assert cursor.fetchone() == (True,)


def test_temporal_index_exists(connection: psycopg.Connection[tuple[object, ...]]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select indexname
            from pg_indexes
            where schemaname = 'corpus'
            """
        )
        indexes = {row[0] for row in cursor.fetchall()}

    assert "cases_decision_date_idx" in indexes
    assert "cases_court_date_idx" in indexes
    assert "cases_organ_date_idx" in indexes
    assert "passages_fts_idx" in indexes
