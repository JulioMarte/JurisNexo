from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

PUBLIC_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
ORG_A = UUID("00000000-0000-0000-0000-00000000000a")


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def test_public_scope_singleton_exists(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select id, visibility, organization_id
            from corpus.scopes
            where visibility = 'public'
            """
        )
        rows = cursor.fetchall()

    assert rows == [(PUBLIC_SCOPE_ID, "public", None)]


def test_private_scope_requires_organization(
    connection: psycopg.Connection[Any],
) -> None:
    with (
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        cursor.execute("insert into corpus.scopes (visibility) values ('private')")


def test_public_scope_rejects_organization(
    connection: psycopg.Connection[Any],
) -> None:
    with (
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        cursor.execute(
            """
            insert into corpus.scopes (visibility, organization_id)
            values ('public', %s)
            """,
            (ORG_A,),
        )


def test_public_scope_is_singleton(connection: psycopg.Connection[Any]) -> None:
    with (
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.UniqueViolation),
    ):
        cursor.execute("insert into corpus.scopes (visibility) values ('public')")


def test_only_one_private_scope_per_organization(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.scopes (visibility, organization_id)
            values ('private', %s)
            """,
            (ORG_A,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                insert into corpus.scopes (visibility, organization_id)
                values ('private', %s)
                """,
                (ORG_A,),
            )


def test_existing_root_records_default_to_public_scope(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts (sha256, mime_type, byte_size)
            values (repeat('c', 64), 'application/pdf', 10)
            returning scope_id
            """
        )
        assert cursor.fetchone() == (PUBLIC_SCOPE_ID,)

        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction)
            values ('SCOPE-PUBLIC', 'Scope contract public court', 'República Dominicana')
            returning id
            """
        )
        court = cursor.fetchone()
        assert court is not None

        cursor.execute(
            "insert into corpus.cases (court_id) values (%s) returning scope_id",
            (court[0],),
        )
        assert cursor.fetchone() == (PUBLIC_SCOPE_ID,)


def test_private_scope_can_be_assigned_explicitly_to_roots(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.scopes (visibility, organization_id)
            values ('private', %s)
            returning id
            """,
            (ORG_A,),
        )
        private_scope = cursor.fetchone()
        assert private_scope is not None

        cursor.execute(
            """
            insert into corpus.source_artifacts (
                sha256, mime_type, byte_size, scope_id
            )
            values (repeat('d', 64), 'application/pdf', 20, %s)
            returning scope_id
            """,
            (private_scope[0],),
        )
        assert cursor.fetchone() == (private_scope[0],)

        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction)
            values ('SCOPE-PRIVATE', 'Scope contract private court', 'República Dominicana')
            returning id
            """
        )
        court = cursor.fetchone()
        assert court is not None

        cursor.execute(
            """
            insert into corpus.cases (court_id, scope_id)
            values (%s, %s)
            returning scope_id
            """,
            (court[0], private_scope[0]),
        )
        assert cursor.fetchone() == (private_scope[0],)


def test_root_scope_must_reference_a_real_scope(
    connection: psycopg.Connection[Any],
) -> None:
    missing_scope = UUID("00000000-0000-0000-0000-000000000099")
    with (
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        cursor.execute(
            """
            insert into corpus.source_artifacts (
                sha256, mime_type, byte_size, scope_id
            )
            values (repeat('e', 64), 'application/pdf', 30, %s)
            """,
            (missing_scope,),
        )
