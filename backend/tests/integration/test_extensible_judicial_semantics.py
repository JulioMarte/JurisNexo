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
            RETURNING opinion_type,opinion_type_concept_id
            """,
            (decision, concept),
        )
        assert cursor.fetchone() == (code, concept)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_opinions(
                    case_id,opinion_type,opinion_type_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,'majority',%s,'verified','primary_text')
                """,
                (decision, concept),
            )


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
            RETURNING stance_type,stance_concept_id
            """,
            (vote, decision, officer, concept),
        )
        assert cursor.fetchone() == (code, concept)


def test_judicial_authority_effects_are_extensible_and_compat_view_survives(
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
            RETURNING id,authority_type
            """,
            (decision, concept, court),
        )
        assertion, mirrored_code = cursor.fetchone() or (None, None)
        assert mirrored_code == code
        cursor.execute(
            "SELECT authority_effect_concept_id FROM corpus.precedential_authority_assertions "
            "WHERE id=%s",
            (assertion,),
        )
        assert cursor.fetchone() == (concept,)


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
        for target_type, column, target_id, effect_code in targets:
            effect = _effect(cursor, target_type, effect_code)
            cursor.execute(
                f"""
                INSERT INTO corpus.disposition_targets(
                    disposition_id,target_type,{column},effect_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,%s,%s,'verified','primary_text')
                """,
                (disposition, target_type, target_id, effect),
            )

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

        claim_effect = _effect(cursor, "claim", "denied")
        with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,target_type,target_decision_id,effect_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,'decision',%s,%s,'verified','primary_text')
                """,
                (disposition, reviewed, claim_effect),
            )


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
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,target_type,target_party_role_id,effect_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,'party',%s,%s,'verified','primary_text')
                """,
                (disposition, unrelated_role, party_effect),
            )

        proposition_effect = _effect(cursor, "proposition", "rejects")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,target_type,target_proposition_id,effect_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,'proposition',%s,%s,'verified','primary_text')
                """,
                (disposition, unrelated_prop, proposition_effect),
            )


def test_claim_compatibility_views_do_not_create_second_truth(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Proceso compatibilidad")
        _link_proceeding_decision(cursor, proceeding, decision)
        claim = _claim(cursor, proceeding)
        disposition = _disposition(cursor, decision)
        cursor.execute("SELECT id FROM corpus.claim_effect_concepts WHERE code='granted'")
        effect = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_claim_effects(
                disposition_id,claim_id,effect_concept_id,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,'verified','primary_text')
            """,
            (disposition, claim, effect),
        )
        cursor.execute(
            """
            SELECT target_type,target_claim_id
            FROM corpus.disposition_targets
            WHERE disposition_id=%s AND target_claim_id=%s
            """,
            (disposition, claim),
        )
        assert cursor.fetchone() == ("claim", claim)
