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


def test_disposition_effects_remain_extensible_without_single_target_type(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        code = f"do_effect_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO corpus.disposition_effect_concepts(code,name)
            VALUES (%s,'Efecto dispositivo local') RETURNING id
            """,
            (code,),
        )
        assert _one(cursor) is not None
        cursor.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='disposition_effect_concepts'
              AND column_name='target_type'
            """
        )
        assert _one(cursor) == 0

        cursor.execute("SELECT to_regclass('corpus.disposition_targets')")
        assert _one(cursor) is None
        cursor.execute(
            "SELECT to_regclass('corpus.judicial_disposition_action_arguments')"
        )
        assert _one(cursor) is not None
