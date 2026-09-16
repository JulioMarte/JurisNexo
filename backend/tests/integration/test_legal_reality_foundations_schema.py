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


def _court(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex[:10]
    cursor.execute(
        """
        INSERT INTO corpus.courts (code, name, jurisdiction)
        VALUES (%s, %s, 'República Dominicana')
        RETURNING id
        """,
        (f"DO-REALITY-{suffix}", f"Tribunal realidad {suffix}"),
    )
    return _one(cursor)


def _case(cursor: psycopg.Cursor[Any], court_id: Any, *, scope_id: Any | None = None) -> Any:
    if scope_id is None:
        cursor.execute(
            "INSERT INTO corpus.cases (court_id) VALUES (%s) RETURNING id",
            (court_id,),
        )
    else:
        cursor.execute(
            "INSERT INTO corpus.cases (court_id, scope_id) VALUES (%s, %s) RETURNING id",
            (court_id, scope_id),
        )
    return _one(cursor)


def test_repeated_provision_labels_are_unique_only_among_siblings(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_documents (document_type, title, identity_status)
            VALUES ('statute', 'Ley de prueba estructural', 'canonical')
            RETURNING id
            """
        )
        document_id = _one(cursor)

        parents: list[Any] = []
        for label in ("Artículo 10", "Artículo 11"):
            cursor.execute(
                """
                INSERT INTO corpus.legal_document_provisions (
                    document_id, provision_type, label, normalized_label
                ) VALUES (%s, 'article', %s, %s)
                RETURNING id
                """,
                (document_id, label, label.lower().replace(" ", "-")),
            )
            parents.append(_one(cursor))

        for parent_id in parents:
            cursor.execute(
                """
                INSERT INTO corpus.legal_document_provisions (
                    document_id, parent_provision_id, provision_type,
                    label, normalized_label
                ) VALUES (%s, %s, 'paragraph', 'Párrafo I', 'parrafo-i')
                """,
                (document_id, parent_id),
            )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_document_provisions (
                    document_id, parent_provision_id, provision_type,
                    label, normalized_label
                ) VALUES (%s, %s, 'paragraph', 'Párrafo I', 'parrafo-i')
                """,
                (document_id, parents[0]),
            )


def test_one_controversy_can_span_multiple_court_proceedings(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_controversies (
                canonical_title, status, identity_status
            ) VALUES ('Pérez contra Ejemplo, S.R.L.', 'active', 'canonical')
            RETURNING id
            """
        )
        controversy_id = _one(cursor)

        for title in ("Primer grado", "Apelación"):
            cursor.execute(
                """
                INSERT INTO corpus.legal_proceedings (
                    controversy_id, originating_court_id, canonical_title,
                    identity_status
                ) VALUES (%s, %s, %s, 'canonical')
                """,
                (controversy_id, court_id, title),
            )

        cursor.execute(
            "SELECT count(*) FROM corpus.legal_proceedings WHERE controversy_id = %s",
            (controversy_id,),
        )
        assert cursor.fetchone() == (2,)


def test_cross_scope_controversy_link_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        organization_id = uuid4()
        cursor.execute(
            """
            INSERT INTO corpus.scopes (visibility, organization_id)
            VALUES ('private', %s)
            RETURNING id
            """,
            (organization_id,),
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


def test_procedural_event_preserves_raw_description_and_date_uncertainty(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (canonical_title, identity_status)
            VALUES ('Expediente de evento', 'canonical')
            RETURNING id
            """
        )
        proceeding_id = _one(cursor)
        raw = "Fue depositado un escrito incidental cuya fecha no consta con certeza."
        cursor.execute(
            """
            INSERT INTO corpus.procedural_events (
                proceeding_id, event_type, event_type_raw, raw_description,
                date_status, verification_status, verification_method
            ) VALUES (
                %s, 'other', 'depósito de escrito incidental', %s,
                'unknown', 'candidate', 'llm_extracted'
            )
            RETURNING occurred_on, date_status, event_type_raw, raw_description
            """,
            (proceeding_id, raw),
        )
        assert cursor.fetchone() == (
            None,
            "unknown",
            "depósito de escrito incidental",
            raw,
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO corpus.procedural_events (
                    proceeding_id, event_type, date_status,
                    verification_status, verification_method
                ) VALUES (
                    %s, 'hearing', 'verified_primary_text',
                    'verified', 'primary_text'
                )
                """,
                (proceeding_id,),
            )


def test_decision_panel_keeps_officer_identity_separate_from_role(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor)
        case_id = _case(cursor, court_id)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_officers (
                display_name, normalized_name, identity_status
            ) VALUES ('Magistrada Ejemplo', 'magistrada ejemplo', 'canonical')
            RETURNING id
            """
        )
        officer_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members (
                case_id, officer_id, role_raw, panel_role, ordinal,
                verification_status, verification_method
            ) VALUES (
                %s, %s, 'Jueza ponente', 'ponente', 1,
                'verified', 'primary_text'
            )
            RETURNING role_raw, panel_role
            """,
            (case_id, officer_id),
        )
        assert cursor.fetchone() == ("Jueza ponente", "ponente")


def test_legal_proposition_keeps_interpretation_distinct_from_source_evidence(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor)
        case_id = _case(cursor, court_id)

        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                proposition_type, canonical_text, assertion_kind,
                verification_status, confidence
            ) VALUES (
                'holding',
                'La acción no estaba prescrita.',
                'synthesized_interpretation',
                'candidate',
                0.84
            )
            RETURNING id
            """
        )
        proposition_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_proposition_evidence (
                proposition_id, source_case_id, evidence_role,
                exact_excerpt, extraction_method
            ) VALUES (
                %s, %s, 'supports',
                'por tales motivos, se rechaza el medio de prescripción',
                'llm_extracted'
            )
            """,
            (proposition_id, case_id),
        )

        cursor.execute(
            """
            SELECT assertion_kind, verification_status
            FROM corpus.legal_propositions
            WHERE id = %s
            """,
            (proposition_id,),
        )
        assert cursor.fetchone() == ("synthesized_interpretation", "candidate")
        cursor.execute(
            """
            SELECT source_case_id, evidence_role, exact_excerpt
            FROM corpus.legal_proposition_evidence
            WHERE proposition_id = %s
            """,
            (proposition_id,),
        )
        assert cursor.fetchone() == (
            case_id,
            "supports",
            "por tales motivos, se rechaza el medio de prescripción",
        )


def test_cross_scope_proposition_relation_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                proposition_type, canonical_text, assertion_kind
            ) VALUES ('issue', 'Cuestión pública', 'human_authored')
            RETURNING id
            """
        )
        public_proposition = _one(cursor)

        organization_id = uuid4()
        cursor.execute(
            """
            INSERT INTO corpus.scopes (visibility, organization_id)
            VALUES ('private', %s)
            RETURNING id
            """,
            (organization_id,),
        )
        private_scope = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions (
                scope_id, proposition_type, canonical_text, assertion_kind
            ) VALUES (%s, 'holding', 'Conclusión privada', 'human_authored')
            RETURNING id
            """,
            (private_scope,),
        )
        private_proposition = _one(cursor)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_proposition_relations (
                    scope_id, from_proposition_id, relation_type,
                    to_proposition_id, verification_method
                ) VALUES (%s, %s, 'answers', %s, 'contract_test')
                """,
                (private_scope, private_proposition, public_proposition),
            )
