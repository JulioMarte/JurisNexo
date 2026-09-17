from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

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
        (f"DO-EXT-{suffix}", f"Tribunal extensible {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _proceeding(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_proceedings(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def _link_proceeding_decision(
    cursor: psycopg.Cursor[Any], proceeding: Any, decision: Any
) -> None:
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_decisions(
            proceeding_id,case_id,relation_type,
            verification_status,verification_method
        ) VALUES (%s,%s,'decision_in_proceeding','verified','primary_text')
        """,
        (proceeding, decision),
    )


def _party_role(cursor: psycopg.Cursor[Any], proceeding: Any, name: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.participants(participant_kind,display_name) "
        "VALUES ('person',%s) RETURNING id",
        (name,),
    )
    participant = _one(cursor)
    cursor.execute(
        "SELECT id FROM corpus.procedural_role_concepts WHERE code='appellant'"
    )
    role_concept = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_party_roles(
            proceeding_id,participant_id,role_concept_id,
            verification_status,verification_method
        ) VALUES (%s,%s,%s,'verified','primary_text') RETURNING id
        """,
        (proceeding, participant, role_concept),
    )
    return _one(cursor)


def _claim(cursor: psycopg.Cursor[Any], proceeding: Any) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.legal_claim_concepts WHERE code='appeal_ground'"
    )
    concept = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_claims(
            proceeding_id,claim_concept_id,claim_text,
            verification_status,verification_method
        ) VALUES (%s,%s,'Medio de prueba','verified','primary_text') RETURNING id
        """,
        (proceeding, concept),
    )
    return _one(cursor)


def _proposition(cursor: psycopg.Cursor[Any], decision: Any, text: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions(
            proposition_type,canonical_text,assertion_kind,verification_status
        ) VALUES ('holding',%s,'derived_from_primary_text','verified') RETURNING id
        """,
        (text,),
    )
    proposition = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_proposition_subjects(
            proposition_id,subject_type,judicial_decision_id
        ) VALUES (%s,'judicial_decision',%s)
        """,
        (proposition, decision),
    )
    return proposition


def _disposition(cursor: psycopg.Cursor[Any], decision: Any) -> Any:
    cursor.execute("SELECT id FROM corpus.disposition_concepts WHERE code='other'")
    concept = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decision_dispositions(
            case_id,ordinal,disposition_concept_id,raw_text,
            extraction_method,verification_status
        ) VALUES (%s,1,%s,'POR TANTO','human','verified') RETURNING id
        """,
        (decision, concept),
    )
    return _one(cursor)


def _effect(cursor: psycopg.Cursor[Any], target_type: str, code: str) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.disposition_effect_concepts "
        "WHERE target_type=%s AND code=%s",
        (target_type, code),
    )
    return _one(cursor)


def _action(
    cursor: psycopg.Cursor[Any], disposition: Any, effect: Any, ordinal: int
) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.judicial_disposition_actions(
            disposition_id,effect_concept_id,ordinal,
            verification_status,verification_method
        ) VALUES (%s,%s,%s,'verified','primary_text') RETURNING id
        """,
        (disposition, effect, ordinal),
    )
    return _one(cursor)


def test_opinion_types_are_extensible_concepts(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        code = f"do_opinion_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinion_type_concepts(code,name,description)
            VALUES (%s,'Voto motivado local','Concepto jurisdiccional no common-law')
            RETURNING id
            """,
            (code,),
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinions(
                case_id,opinion_type_concept_id,
                verification_status,verification_method
            ) VALUES (%s,%s,'verified','primary_text')
            RETURNING opinion_type_concept_id
            """,
            (decision, concept),
        )
        assert _one(cursor) == concept


def test_judicial_stances_are_extensible_concepts(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        cursor.execute(
            "INSERT INTO corpus.judicial_officers(display_name) "
            "VALUES ('Magistrada postura extensible') RETURNING id"
        )
        officer = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members(
                case_id,officer_id,role_raw,panel_role,
                verification_status,verification_method
            ) VALUES (%s,%s,'Miembro','member','verified','primary_text')
            """,
            (decision, officer),
        )
        cursor.execute(
            """
            INSERT INTO corpus.decision_votes(
                case_id,officer_id,vote_type,
                verification_status,verification_method
            ) VALUES (%s,%s,'concurring','verified','primary_text') RETURNING id
            """,
            (decision, officer),
        )
        vote = _one(cursor)
        code = f"do_stance_{uuid4().hex[:8]}"
        cursor.execute(
            "INSERT INTO corpus.judicial_stance_concepts(code,name) "
            "VALUES (%s,'Reserva especial local') RETURNING id",
            (code,),
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_vote_stances(
                vote_id,case_id,officer_id,stance_concept_id,scope_type,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,%s,'whole_decision','verified','primary_text')
            RETURNING stance_concept_id
            """,
            (vote, decision, officer, concept),
        )
        assert _one(cursor) == concept


def test_judicial_authority_effects_are_extensible_without_compat_alias(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        code = f"do_authority_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO corpus.judicial_authority_effect_concepts(code,name,description)
            VALUES (%s,'Efecto jurisprudencial local','No presupone binding/persuasive')
            RETURNING id
            """,
            (code,),
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_authority_assertions(
                decision_id,authority_effect_concept_id,court_id,basis,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,'Contexto de prueba','verified','human_legal_review')
            RETURNING authority_effect_concept_id
            """,
            (decision, concept, court),
        )
        assert _one(cursor) == concept
        cursor.execute("SELECT to_regclass('corpus.precedential_authority_assertions')")
        assert _one(cursor) is None


def test_disposition_targets_cover_claim_party_proceeding_decision_and_proposition(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        reviewed = _decision(cursor, court)
        source_proceeding = _proceeding(cursor, "Proceso fuente")
        remand_proceeding = _proceeding(cursor, "Proceso de reenvío")
        _link_proceeding_decision(cursor, source_proceeding, source)
        party_role = _party_role(cursor, source_proceeding, "Parte objetivo")
        claim = _claim(cursor, source_proceeding)
        proposition = _proposition(cursor, source, "Proposición objetivo del dispositivo")
        disposition = _disposition(cursor, source)

        targets = (
            ("claim", "target_claim_id", claim, "granted"),
            ("party", "target_party_role_id", party_role, "orders"),
            ("proceeding", "target_proceeding_id", remand_proceeding, "remands"),
            ("decision", "target_decision_id", reviewed, "reverses"),
            ("proposition", "target_proposition_id", proposition, "adopts"),
        )
        for ordinal, (target_type, column, target_id, effect_code) in enumerate(
            targets, start=1
        ):
            effect = _effect(cursor, target_type, effect_code)
            action = _action(cursor, disposition, effect, ordinal)
            query = sql.SQL(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,action_id,target_type,{},
                    verification_status,verification_method
                ) VALUES (%s,%s,%s,%s,'verified','primary_text')
                """
            ).format(sql.Identifier(column))
            cursor.execute(query, (disposition, action, target_type, target_id))

        cursor.execute(
            "SELECT target_type FROM corpus.disposition_targets "
            "WHERE disposition_id=%s ORDER BY target_type",
            (disposition,),
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "claim",
            "decision",
            "party",
            "proceeding",
            "proposition",
        ]


def test_disposition_party_and_proposition_targets_reject_unrelated_context(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        unrelated_decision = _decision(cursor, court)
        source_proceeding = _proceeding(cursor, "Proceso relacionado")
        unrelated_proceeding = _proceeding(cursor, "Proceso ajeno")
        _link_proceeding_decision(cursor, source_proceeding, source)
        unrelated_role = _party_role(cursor, unrelated_proceeding, "Parte ajena")
        unrelated_prop = _proposition(
            cursor, unrelated_decision, "Proposición de otra sentencia"
        )
        disposition = _disposition(cursor, source)

        party_effect = _effect(cursor, "party", "orders")
        party_action = _action(cursor, disposition, party_effect, 1)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,action_id,target_type,target_party_role_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,'party',%s,'verified','primary_text')
                """,
                (disposition, party_action, unrelated_role),
            )

        proposition_effect = _effect(cursor, "proposition", "rejects")
        proposition_action = _action(cursor, disposition, proposition_effect, 2)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,action_id,target_type,target_proposition_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,'proposition',%s,'verified','primary_text')
                """,
                (disposition, proposition_action, unrelated_prop),
            )


def test_claim_disposition_effect_uses_canonical_action_target_only(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Proceso canónico")
        _link_proceeding_decision(cursor, proceeding, decision)
        claim = _claim(cursor, proceeding)
        disposition = _disposition(cursor, decision)
        effect = _effect(cursor, "claim", "granted")
        action = _action(cursor, disposition, effect, 1)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_targets(
                disposition_id,action_id,target_type,target_claim_id,
                verification_status,verification_method
            ) VALUES (%s,%s,'claim',%s,'verified','primary_text')
            """,
            (disposition, action, claim),
        )
        cursor.execute(
            """
            SELECT a.effect_concept_id,t.target_claim_id
            FROM corpus.disposition_targets t
            JOIN corpus.judicial_disposition_actions a ON a.id=t.action_id
            WHERE t.disposition_id=%s AND t.target_claim_id=%s
            """,
            (disposition, claim),
        )
        assert cursor.fetchone() == (effect, claim)
        cursor.execute("SELECT to_regclass('corpus.disposition_claim_effects')")
        assert _one(cursor) is None
