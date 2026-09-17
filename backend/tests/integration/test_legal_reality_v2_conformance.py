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
        "INSERT INTO corpus.courts(code,name,jurisdiction) "
        "VALUES (%s,%s,'DO') RETURNING id",
        (f"DO-CONF-{suffix}", f"Tribunal Conformance {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _proposition(cursor: psycopg.Cursor[Any], text: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions(
            proposition_type, canonical_text, assertion_kind, verification_status
        ) VALUES ('holding', %s, 'derived_from_primary_text', 'candidate')
        RETURNING id
        """,
        (text,),
    )
    return _one(cursor)


def _proceeding(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_proceedings(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def _controversy(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_controversies(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def test_decision_classification_uses_only_canonical_relation_tables(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        matter_ids: list[Any] = []
        procedure_ids: list[Any] = []
        for prefix, target in (
            ("matter", matter_ids),
            ("procedure", procedure_ids),
        ):
            for label in ("A", "B"):
                code = f"{prefix}_{uuid4().hex[:10]}"
                table = (
                    "corpus.legal_matter_concepts"
                    if prefix == "matter"
                    else "corpus.procedure_concepts"
                )
                cursor.execute(
                    f"INSERT INTO {table}(code,name) VALUES (%s,%s) RETURNING id",
                    (code, f"{prefix} {label}"),
                )
                target.append(_one(cursor))

        court = _court(cursor)
        decision = _decision(cursor, court)
        for ordinal, matter in enumerate(matter_ids, start=1):
            cursor.execute(
                """
                INSERT INTO corpus.decision_legal_matters(
                    decision_id, legal_matter_concept_id, relation_type, ordinal,
                    verification_status, verification_method
                ) VALUES (%s,%s,'addresses',%s,'verified','human_review')
                """,
                (decision, matter, ordinal),
            )
        for ordinal, procedure in enumerate(procedure_ids, start=1):
            cursor.execute(
                """
                INSERT INTO corpus.decision_procedures(
                    decision_id, procedure_concept_id, relation_type, ordinal,
                    verification_status, verification_method
                ) VALUES (%s,%s,'applies',%s,'verified','human_review')
                """,
                (decision, procedure, ordinal),
            )

        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='corpus' AND table_name='judicial_decisions'
              AND column_name IN ('legal_matter_concept_id','procedure_concept_id')
            """
        )
        assert cursor.fetchall() == []
        cursor.execute(
            "SELECT count(*) FROM corpus.decision_legal_matters WHERE decision_id=%s",
            (decision,),
        )
        assert cursor.fetchone() == (2,)
        cursor.execute(
            "SELECT count(*) FROM corpus.decision_procedures WHERE decision_id=%s",
            (decision,),
        )
        assert cursor.fetchone() == (2,)


def test_controversy_membership_uses_open_role_concept_without_scalar_alias(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        controversy = _controversy(cursor, "Controversia canónica")
        proceeding = _proceeding(cursor, "Procedimiento canónico")
        cursor.execute(
            "SELECT id FROM corpus.controversy_membership_role_concepts "
            "WHERE code='originating'"
        )
        role = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.controversy_proceedings(
                controversy_id, proceeding_id, relation_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,'verified','human_review')
            """,
            (controversy, proceeding, role),
        )
        cursor.execute(
            """
            SELECT c.code
            FROM corpus.controversy_proceedings cp
            JOIN corpus.controversy_membership_role_concepts c
              ON c.id=cp.relation_concept_id
            WHERE cp.proceeding_id=%s
            """,
            (proceeding,),
        )
        assert cursor.fetchone() == ("originating",)
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='corpus' AND table_name='legal_proceedings'
              AND column_name='controversy_id'
            """
        )
        assert cursor.fetchone() is None


def test_proposition_scoped_stance_must_target_same_decision(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        other_decision = _decision(cursor, court)
        cursor.execute(
            "INSERT INTO corpus.judicial_officers(display_name,identity_status) "
            "VALUES ('Magistrada de prueba','canonical') RETURNING id"
        )
        officer = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members(
                case_id, officer_id, role_raw, panel_role,
                verification_status, verification_method
            ) VALUES (%s,%s,'Miembro','member','verified','primary_text')
            """,
            (decision, officer),
        )
        cursor.execute(
            """
            INSERT INTO corpus.decision_votes(
                case_id, officer_id, vote_type,
                verification_status, verification_method
            ) VALUES (%s,%s,'concurring','verified','primary_text') RETURNING id
            """,
            (decision, officer),
        )
        vote = _one(cursor)
        proposition = _proposition(cursor, "Cuestión que pertenece a otra sentencia")
        cursor.execute(
            """
            INSERT INTO corpus.legal_proposition_subjects(
                proposition_id, subject_type, judicial_decision_id
            ) VALUES (%s,'judicial_decision',%s)
            """,
            (proposition, other_decision),
        )
        cursor.execute(
            "SELECT id FROM corpus.judicial_stance_concepts "
            "WHERE code='dissents_in_part'"
        )
        stance = _one(cursor)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_vote_stances(
                    vote_id, case_id, officer_id, stance_concept_id, scope_type,
                    proposition_id, verification_status, verification_method
                ) VALUES (%s,%s,%s,%s,'proposition',%s,
                          'verified','primary_text')
                """,
                (vote, decision, officer, stance, proposition),
            )

        cursor.execute(
            """
            INSERT INTO corpus.legal_proposition_subjects(
                proposition_id, subject_type, judicial_decision_id, ordinal
            ) VALUES (%s,'judicial_decision',%s,2)
            """,
            (proposition, decision),
        )
        cursor.execute(
            """
            INSERT INTO corpus.judicial_vote_stances(
                vote_id, case_id, officer_id, stance_concept_id, scope_type,
                proposition_id, verification_status, verification_method
            ) VALUES (%s,%s,%s,%s,'proposition',%s,
                      'verified','primary_text')
            """,
            (vote, decision, officer, stance, proposition),
        )


def test_claim_parent_and_asserting_party_must_belong_to_same_proceeding(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first = _proceeding(cursor, "Procedimiento A")
        second = _proceeding(cursor, "Procedimiento B")
        cursor.execute(
            """
            INSERT INTO corpus.participants(participant_kind,display_name)
            VALUES ('person','Parte de procedimiento B') RETURNING id
            """
        )
        participant = _one(cursor)
        cursor.execute(
            "SELECT id FROM corpus.procedural_role_concepts WHERE code='appellant'"
        )
        role_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_party_roles(
                proceeding_id, participant_id, role_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,'verified','official_metadata')
            RETURNING id
            """,
            (second, participant, role_concept),
        )
        second_role = _one(cursor)
        cursor.execute(
            "SELECT id FROM corpus.legal_claim_concepts WHERE code='appeal_ground'"
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_claims(
                proceeding_id, claim_concept_id, claim_text,
                verification_status, verification_method
            ) VALUES (%s,%s,'Medio padre','verified','primary_text') RETURNING id
            """,
            (second, concept),
        )
        second_claim = _one(cursor)

        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_claims(
                    proceeding_id, asserted_by_party_role_id,
                    claim_concept_id, claim_text,
                    verification_status, verification_method
                ) VALUES (%s,%s,%s,'Rol ajeno','candidate','test')
                """,
                (first, second_role, concept),
            )

        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_claims(
                    proceeding_id, parent_claim_id,
                    claim_concept_id, claim_text,
                    verification_status, verification_method
                ) VALUES (%s,%s,%s,'Padre ajeno','candidate','test')
                """,
                (first, second_claim, concept),
            )


def test_decision_events_and_durative_states_are_not_interchangeable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)

        cursor.execute(
            "SELECT count(*) FROM corpus.judicial_event_type_concepts WHERE code='final'"
        )
        assert cursor.fetchone() == (0,)
        cursor.execute(
            "SELECT id FROM corpus.decision_state_concepts WHERE code='final'"
        )
        final_state = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_states(
                decision_id, state_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,'verified','official_metadata')
            """,
            (decision, final_state),
        )

        cursor.execute(
            "SELECT count(*) FROM corpus.decision_state_concepts "
            "WHERE code IN ('vacated','annulled','reversed','partially_reversed')"
        )
        assert cursor.fetchone() == (0,)
        cursor.execute(
            "SELECT id FROM corpus.judicial_event_type_concepts WHERE code='reversed'"
        )
        reversed_event = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_status_events(
                case_id, event_type_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,'verified','official_metadata')
            """,
            (decision, reversed_event),
        )
