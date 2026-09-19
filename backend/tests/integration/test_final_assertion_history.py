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
    pytest.mark.temporal,
    pytest.mark.security,
]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _private_scope(cursor: psycopg.Cursor[Any]) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.scopes (visibility, organization_id)
        VALUES ('private', %s) RETURNING id
        """,
        (uuid4(),),
    )
    return _one(cursor)


def _document(cursor: psycopg.Cursor[Any], scope_id: Any, title: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_documents (
            scope_id, document_type, title, country_code, identity_status
        ) VALUES (%s, 'statute', %s, 'DO', 'canonical') RETURNING id
        """,
        (scope_id, title),
    )
    return _one(cursor)


def test_relation_identity_cannot_cross_corpus_scopes(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        private_scope = _private_scope(cursor)
        private_document = _document(cursor, private_scope, "Privado")
        cursor.execute(
            """
            INSERT INTO corpus.legal_documents (
                document_type, title, country_code, identity_status
            ) VALUES ('statute', 'Público', 'DO', 'canonical') RETURNING id
            """
        )
        public_document = _one(cursor)
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation
        ), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_relation_identities (
                    source_document_id, relation_type, target_document_id
                ) VALUES (%s, 'references', %s)
                """,
                (private_document, public_document),
            )


def test_norm_source_scope_is_derived_and_cross_scope_source_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        private_scope = _private_scope(cursor)
        private_document = _document(cursor, private_scope, "Fuente privada")
        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                proposition_type, canonical_text,
                assertion_kind, verification_status
            ) VALUES (
                'legal_requirement', 'Norma pública',
                'synthesized_interpretation', 'candidate'
            ) RETURNING id
            """
        )
        proposition = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_norm_assertions (
                proposition_id, norm_kind, derivation_kind,
                verification_method
            ) VALUES (
                %s, 'test', 'synthesized_interpretation', 'test'
            ) RETURNING id
            """,
            (proposition,),
        )
        assertion = _one(cursor)
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation
        ), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_norm_sources (
                    norm_assertion_id, source_document_id, source_role,
                    verification_status, verification_method
                ) VALUES (
                    %s, %s, 'evidences', 'candidate', 'test'
                )
                """,
                (assertion, private_document),
            )


def test_norm_knowledge_intervals_cannot_overlap(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                proposition_type, canonical_text,
                assertion_kind, verification_status
            ) VALUES (
                'legal_requirement', 'Norma temporal',
                'synthesized_interpretation', 'candidate'
            ) RETURNING id
            """
        )
        proposition = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_norm_assertions (
                proposition_id, norm_kind, derivation_kind,
                known_from, known_to, verification_method
            ) VALUES (
                %s, 'test', 'synthesized_interpretation',
                '2025-01-01Z', '2025-07-01Z', 'test'
            )
            """,
            (proposition,),
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_norm_assertions (
                    proposition_id, norm_kind, derivation_kind,
                    known_from, known_to, verification_method
                ) VALUES (
                    %s, 'test', 'synthesized_interpretation',
                    '2025-06-01Z', '2025-09-01Z', 'test'
                )
                """,
                (proposition,),
            )


def test_treatment_knowledge_intervals_cannot_overlap(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        suffix = uuid4().hex[:8]
        cursor.execute(
            """
            INSERT INTO corpus.courts (code, name, jurisdiction)
            VALUES (%s, %s, 'DO') RETURNING id
            """,
            (f"DO-HIST-{suffix}", f"Tribunal {suffix}"),
        )
        court = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions (court_id)
            VALUES (%s), (%s) RETURNING id
            """,
            (court, court),
        )
        source, target = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            """
            INSERT INTO corpus.legal_issues(
                canonical_question, assertion_kind,
                verification_status, verification_method
            ) VALUES (
                'Cuestión temporal', 'human_authored',
                'candidate', 'test'
            ) RETURNING id
            """
        )
        issue = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_treatment_assertions (
                source_case_id, target_case_id, treatment_type,
                legal_issue_id, known_from, known_to,
                verification_status, verification_method
            ) VALUES (
                %s, %s, 'distinguishes', %s,
                '2025-01-01Z', '2025-08-01Z', 'candidate', 'test'
            )
            """,
            (source, target, issue),
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_treatment_assertions (
                    source_case_id, target_case_id, treatment_type,
                    legal_issue_id, known_from, known_to,
                    verification_status, verification_method
                ) VALUES (
                    %s, %s, 'distinguishes', %s,
                    '2025-07-01Z', '2025-10-01Z', 'candidate', 'test'
                )
                """,
                (source, target, issue),
            )
