from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _scalar(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _resolution_graph(
    cursor: psycopg.Cursor[Any],
    suffix: str,
    *,
    status: str = "parsed_high_confidence",
    selected: bool = True,
) -> dict[str, Any]:
    cursor.execute(
        """
        insert into corpus.source_registries (code, name, institution, authority_class)
        values (%s, %s, 'Poder Judicial', 'official_primary') returning id
        """,
        (f"PROM-{suffix}", f"Promotion registry {suffix}"),
    )
    registry_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.source_artifacts (
            source_registry_id, sha256, mime_type, byte_size, page_count
        ) values (%s, %s, 'application/pdf', 100, 1) returning id
        """,
        (registry_id, (suffix.lower() * 64)[:64]),
    )
    artifact_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.artifact_pages (
            artifact_id, page_number, extracted_text, extraction_status
        ) values (%s, 1, 'en fecha 30 de abril de 2025 dicta la siguiente sentencia', 'native_text')
        returning id
        """,
        (artifact_id,),
    )
    artifact_page_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.courts (code, name, jurisdiction)
        values (%s, %s, 'República Dominicana') returning id
        """,
        (f"PROM-COURT-{suffix}", f"Promotion court {suffix}"),
    )
    court_id = _scalar(cursor)
    cursor.execute("insert into corpus.cases (court_id) values (%s) returning id", (court_id,))
    case_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.case_pages (case_id, artifact_id, artifact_page_id, ordinal_in_case)
        values (%s, %s, %s, 1) returning id
        """,
        (case_id, artifact_id, artifact_page_id),
    )
    case_page_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.parser_versions (parser_name, parser_version, code_revision)
        values ('promotion-test', %s, 'test-revision') returning id
        """,
        (suffix,),
    )
    parser_version_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.ingestion_jobs (artifact_id, parser_version_id, idempotency_key)
        values (%s, %s, %s) returning id
        """,
        (artifact_id, parser_version_id, f"promotion-job:{suffix}"),
    )
    job_id = _scalar(cursor)
    observation_key = hashlib_sha(suffix)
    cursor.execute(
        """
        insert into corpus.case_metadata_observations (
            ingestion_job_id, artifact_id, case_id, observation_key,
            field_name, value_type, raw_value, normalized_date,
            observation_method, method_name, evidence_case_page_id
        ) values (
            %s, %s, %s, %s, 'decision_date', 'date',
            '30 de abril de 2025', date '2025-04-30',
            'deterministic_parser', 'promotion_test_v1', %s
        ) returning id
        """,
        (job_id, artifact_id, case_id, observation_key, case_page_id),
    )
    observation_id = _scalar(cursor)
    cursor.execute(
        """
        insert into corpus.case_metadata_resolutions (
            case_id, field_name, value_type, resolved_date, resolution_status,
            resolver_name, resolver_version, code_revision, idempotency_key
        ) values (
            %s, 'decision_date', 'date', date '2025-04-30', %s,
            'decision_date_reconciler', '1', 'test-revision', %s
        ) returning id
        """,
        (case_id, status, hashlib_sha("resolution-" + suffix)),
    )
    resolution_id = _scalar(cursor)
    if selected:
        cursor.execute(
            """
            insert into corpus.case_metadata_resolution_observations (
                resolution_id, case_id, observation_id, role
            ) values (%s, %s, %s, 'selected')
            """,
            (resolution_id, case_id, observation_id),
        )
    return {
        "case_id": case_id,
        "case_page_id": case_page_id,
        "resolution_id": resolution_id,
        "status": status,
    }


def hashlib_sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _insert_promotion(
    cursor: psycopg.Cursor[Any],
    graph: dict[str, Any],
    suffix: str,
    *,
    promoted_date: str = "2025-04-30",
) -> Any:
    cursor.execute(
        """
        insert into corpus.case_metadata_promotions (
            case_id, resolution_id, field_name,
            previous_date, promoted_date, previous_status, promoted_status,
            promotion_method, code_revision, idempotency_key
        ) values (
            %s, %s, 'decision_date', null, %s::date, 'unknown', %s,
            'automatic_reconciler', 'test-revision', %s
        ) returning id
        """,
        (
            graph["case_id"],
            graph["resolution_id"],
            promoted_date,
            graph["status"],
            hashlib_sha("promotion-" + suffix),
        ),
    )
    return _scalar(cursor)


def test_promotion_schema_exists(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("select to_regclass('corpus.case_metadata_promotions')")
        assert cursor.fetchone() == ("corpus.case_metadata_promotions",)
        cursor.execute(
            """
            select is_nullable from information_schema.columns
            where table_schema='corpus' and table_name='cases'
              and column_name='decision_date_resolution_id'
            """
        )
        assert cursor.fetchone() == ("YES",)


def test_eligible_resolution_with_selected_evidence_can_be_promoted(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _resolution_graph(cursor, "a")
        promotion_id = _insert_promotion(cursor, graph, "a")
        assert promotion_id is not None


def test_unverified_resolution_cannot_be_promoted(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _resolution_graph(cursor, "b", status="parsed_unverified")
        with pytest.raises(psycopg.errors.RaiseException):
            _insert_promotion(cursor, graph, "b")


def test_promotion_date_must_match_resolution(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _resolution_graph(cursor, "c")
        with pytest.raises(psycopg.errors.RaiseException):
            _insert_promotion(cursor, graph, "c", promoted_date="2025-04-29")


def test_promotion_requires_selected_page_evidence(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        graph = _resolution_graph(cursor, "d", selected=False)
        with pytest.raises(psycopg.errors.RaiseException):
            _insert_promotion(cursor, graph, "d")


def test_case_current_resolution_cannot_point_to_another_case(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first = _resolution_graph(cursor, "e")
        second = _resolution_graph(cursor, "f")
        cursor.execute("set constraints all immediate")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                update corpus.cases
                set decision_date_resolution_id=%s
                where id=%s
                """,
                (second["resolution_id"], first["case_id"]),
            )
