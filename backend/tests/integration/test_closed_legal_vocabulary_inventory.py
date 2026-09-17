from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_inventory_closed_text_vocabularies(connection: psycopg.Connection[Any]) -> None:
    """Diagnostic inventory for final-schema CHECK-backed text vocabularies.

    This test is intentionally red until the inventory is classified into
    JurisNexo-owned workflow/structural vocabularies versus law-owned concepts.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select
                c.relname as table_name,
                con.conname as constraint_name,
                pg_get_constraintdef(con.oid) as definition
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'corpus'
              and con.contype = 'c'
              and pg_get_constraintdef(con.oid) like '%ANY (ARRAY[%'
            order by c.relname, con.conname
            """
        )
        rows = cursor.fetchall()

    inventory = "\n".join(
        f"{table}.{constraint}: {definition}"
        for table, constraint, definition in rows
    )
    pytest.fail(
        "Closed CHECK-backed vocabularies in the final corpus schema; classify each "
        "as system-owned or replace law-owned categories with concept identities:\n"
        + inventory
    )
