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


def test_legacy_classification_update_replaces_only_legacy_primary_relation(
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
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions(
                court_id, legal_matter_concept_id, procedure_concept_id
            ) VALUES (%s,%s,%s) RETURNING id
            """,
            (court, matter_ids[0], procedure_ids[0]),
        )
        decision = _one(cursor)

        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_matters(
                decision_id, legal_matter_concept_id, relation_type,
                verification_status, verification_method
            ) VALUES (%s,%s,'addresses','verified','human_review')
            """,
            (decision, matter_ids[0]),
        )
        cursor.execute(
            """
            UPDATE corpus.judicial_decisions
            SET legal_matter_concept_id=%s, procedure_concept_id=%s
            WHERE id=%s
            """,
            (matter_ids[1], procedure_ids[1], decision),
        )

        cursor.execute(
            """
            SELECT legal_matter_concept_id, relation_type, verification_method
            FROM corpus.decision_legal_matters
            WHERE decision_id=%s
            ORDER BY relation_type, verification_method
            """,
            (decision,),
        )
        matter_rows = cursor.fetchall()
        assert (matter_ids[0], "addresses", "human_review") in matter_rows
        assert not any(
            row[0] == matter_ids[0] and row[1] == "primary" for row in matter_rows
        )
        assert any(
            row[0] == matter_ids[1] and row[1] == "primary" for row in matter_rows
        )

        cursor.execute(
            """
            SELECT procedure_concept_id
            FROM corpus.decision_procedures
            WHERE decision_id=%s AND relation_type='primary'
            """,
            (decision,),
        )
        assert cursor.fetchall() == [(procedure_ids[1],)]


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

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_vote_stances(
                    vote_id, case_id, officer_id, stance_type, scope_type,
                    proposition_id, verification_status, verification_method
                ) VALUES (%s,%s,%s,'dissents_in_part','proposition',%s,
                          'verified','primary_text')
                """,
                (vote, decision, officer, proposition),
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
                vote_id, case_id, officer_id, stance_type, scope_type,
                proposition_id, verification_status, verification_method
            ) VALUES (%s,%s,%s,'dissents_in_part','proposition',%s,
                      'verified','primary_text')
            """,
            (vote, decision, officer, proposition),
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

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.decision_legal_status_events(
                    case_id, status_type, verification_status, verification_method
                ) VALUES (%s,'final','verified','official_metadata')
                """,
                (decision,),
            )

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
            """
            INSERT INTO corpus.decision_legal_status_events(
                case_id, status_type, verification_status, verification_method
            ) VALUES (%s,'reversed','verified','official_metadata')
            """,
            (decision,),
        )
