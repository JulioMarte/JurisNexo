from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, LiteralString
from uuid import UUID

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

ORG_A = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = UUID("00000000-0000-0000-0000-0000000000bb")


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _insert_scope(cursor: psycopg.Cursor[Any], organization_id: UUID) -> UUID:
    cursor.execute(
        """
        insert into corpus.scopes (visibility, organization_id)
        values ('private', %s)
        returning id
        """,
        (organization_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _insert_court(cursor: psycopg.Cursor[Any], code: str) -> UUID:
    cursor.execute(
        """
        insert into corpus.courts (code, name, jurisdiction)
        values (%s, %s, 'República Dominicana')
        returning id
        """,
        (code, f"{code} court"),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _insert_artifact(
    cursor: psycopg.Cursor[Any], *, scope_id: UUID, sha_char: str
) -> tuple[UUID, UUID]:
    cursor.execute(
        """
        insert into corpus.source_artifacts (
            sha256, mime_type, byte_size, scope_id
        )
        values (%s, 'application/pdf', 100, %s)
        returning id
        """,
        (sha_char * 64, scope_id),
    )
    artifact = cursor.fetchone()
    assert artifact is not None
    cursor.execute(
        """
        insert into corpus.artifact_pages (
            artifact_id, page_number, extracted_text, extraction_status
        )
        values (%s, 1, 'source page', 'native_text')
        returning id
        """,
        (artifact[0],),
    )
    page = cursor.fetchone()
    assert page is not None
    return artifact[0], page[0]


def _insert_case(cursor: psycopg.Cursor[Any], *, scope_id: UUID, court_id: UUID) -> UUID:
    cursor.execute(
        """
        insert into corpus.cases (court_id, scope_id)
        values (%s, %s)
        returning id
        """,
        (court_id, scope_id),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _expect_foreign_key_violation(
    cursor: psycopg.Cursor[Any], sql: LiteralString, params: tuple[object, ...]
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        cursor.execute(sql, params)


def test_same_scope_occurrence_and_case_page_are_allowed(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "SAME-SCOPE")
        artifact_id, artifact_page_id = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="a",
        )
        case_id = _insert_case(cursor, scope_id=scope_id, court_id=court_id)

        cursor.execute(
            """
            insert into corpus.case_artifact_occurrences (
                case_id, artifact_id, start_page, end_page,
                segmentation_status, segmentation_method, scope_id
            )
            values (%s, %s, 1, 1, 'verified', 'contract-test', %s)
            """,
            (case_id, artifact_id, scope_id),
        )
        cursor.execute(
            """
            insert into corpus.case_pages (
                case_id, artifact_id, artifact_page_id, ordinal_in_case, scope_id
            )
            values (%s, %s, %s, 1, %s)
            """,
            (case_id, artifact_id, artifact_page_id, scope_id),
        )


def test_occurrence_cannot_link_case_to_artifact_from_another_scope(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_a = _insert_scope(cursor, ORG_A)
        scope_b = _insert_scope(cursor, ORG_B)
        court_id = _insert_court(cursor, "CROSS-OCC")
        artifact_id, _ = _insert_artifact(cursor, scope_id=scope_a, sha_char="b")
        case_id = _insert_case(cursor, scope_id=scope_b, court_id=court_id)

        _expect_foreign_key_violation(
            cursor,
            """
            insert into corpus.case_artifact_occurrences (
                case_id, artifact_id, start_page, end_page,
                segmentation_status, segmentation_method, scope_id
            )
            values (%s, %s, 1, 1, 'verified', 'contract-test', %s)
            """,
            (case_id, artifact_id, scope_b),
        )


def test_case_page_cannot_link_case_to_artifact_from_another_scope(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_a = _insert_scope(cursor, ORG_A)
        scope_b = _insert_scope(cursor, ORG_B)
        court_id = _insert_court(cursor, "CROSS-PAGE")
        artifact_id, artifact_page_id = _insert_artifact(
            cursor,
            scope_id=scope_a,
            sha_char="c",
        )
        case_id = _insert_case(cursor, scope_id=scope_b, court_id=court_id)

        _expect_foreign_key_violation(
            cursor,
            """
            insert into corpus.case_pages (
                case_id, artifact_id, artifact_page_id,
                ordinal_in_case, scope_id
            )
            values (%s, %s, %s, 1, %s)
            """,
            (case_id, artifact_id, artifact_page_id, scope_b),
        )
