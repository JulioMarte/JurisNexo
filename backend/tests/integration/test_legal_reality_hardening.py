from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest

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


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_controversy_scope_boundary_is_immediate(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.scopes (visibility, organization_id)
            VALUES ('private', %s)
            RETURNING id
            """,
            (uuid4(),),
        )
        private_scope = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_controversies (
                scope_id, canonical_title, identity_status
            ) VALUES (%s, 'Controversia privada', 'canonical')
            RETURNING id
            """,
            (private_scope,),
        )
        private_controversy = _one(cursor)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_proceedings (
                    controversy_id, canonical_title, identity_status
                ) VALUES (%s, 'Procedimiento público imposible', 'canonical')
                """,
                (private_controversy,),
            )


def test_case_page_evidence_requires_case_identity(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_documents (
                document_type, title, identity_status
            ) VALUES ('judicial_decision', 'Documento evidencia', 'canonical')
            RETURNING id
            """
        )
        document_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                proposition_type, canonical_text, assertion_kind
            ) VALUES ('holding', 'Proposición de prueba', 'derived_from_primary_text')
            RETURNING id
            """
        )
        proposition_id = _one(cursor)

        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_proposition_evidence (
                    proposition_id, source_document_id, case_page_id,
                    evidence_role, extraction_method
                ) VALUES (%s, %s, %s, 'supports', 'contract_test')
                """,
                (proposition_id, document_id, uuid4()),
            )
