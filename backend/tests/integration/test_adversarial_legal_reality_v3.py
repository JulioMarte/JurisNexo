from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _proceeding(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_proceedings(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def _court(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO corpus.courts(code,name,jurisdiction) VALUES (%s,%s,'DO') RETURNING id",
        (f"DO-V3-{suffix}", f"Tribunal V3 {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court: Any) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.adjudicative_act_type_concepts WHERE code='decision'"
    )
    act_type = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decisions(court_id,act_type_concept_id)
        VALUES (%s,%s) RETURNING id
        """,
        (court, act_type),
    )
    return _one(cursor)


def _claim(cursor: psycopg.Cursor[Any], proceeding: Any, text: str) -> Any:
    cursor.execute("SELECT id FROM corpus.legal_claim_concepts WHERE code='appeal_ground'")
    concept = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_claims(
            proceeding_id,claim_concept_id,claim_text,
            verification_status,verification_method
        ) VALUES (%s,%s,%s,'verified','primary_text') RETURNING id
        """,
        (proceeding, concept, text),
    )
    return _one(cursor)


def test_proceeding_history_is_an_explicit_directed_graph(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first_instance = _proceeding(cursor, "Primera instancia V3")
        appeal = _proceeding(cursor, "Apelacion V3")
        cassation = _proceeding(cursor, "Casacion V3")
        cursor.execute(
            "SELECT id FROM corpus.proceeding_relation_concepts WHERE code='appeal_of'"
        )
        appeal_of = _one(cursor)
        cursor.execute(
            "SELECT id FROM corpus.proceeding_relation_concepts WHERE code='cassation_of'"
        )
        cassation_of = _one(cursor)

        cursor.execute(
            """
            INSERT INTO corpus.proceeding_relations(
                source_proceeding_id,target_proceeding_id,relation_concept_id,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,'verified','primary_text')
            """,
            (appeal, first_instance, appeal_of),
        )
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_relations(
                source_proceeding_id,target_proceeding_id,relation_concept_id,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,'verified','primary_text')
            """,
            (cassation, appeal, cassation_of),
        )
        cursor.execute(
            """
            SELECT c.code FROM corpus.proceeding_relations r
            JOIN corpus.proceeding_relation_concepts c ON c.id=r.relation_concept_id
            WHERE r.source_proceeding_id IN (%s,%s)
            ORDER BY c.code
            """,
            (appeal, cassation),
        )
        assert [row[0] for row in cursor.fetchall()] == ["appeal_of", "cassation_of"]

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.proceeding_relations(
                    source_proceeding_id,target_proceeding_id,relation_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,%s,'verified','primary_text')
                """,
                (appeal, appeal, appeal_of),
            )


def test_claim_lineage_can_cross_proceedings(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first_instance = _proceeding(cursor, "Claim origen V3")
        appeal = _proceeding(cursor, "Claim apelacion V3")
        original = _claim(cursor, first_instance, "Pretension original")
        appellate = _claim(cursor, appeal, "Medio que impugna la pretension")
        cursor.execute(
            "SELECT id FROM corpus.claim_relation_concepts WHERE code='challenges'"
        )
        relation = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.claim_relations(
                source_claim_id,target_claim_id,relation_concept_id,
                verification_status,verification_method
            ) VALUES (%s,%s,%s,'verified','primary_text') RETURNING id
            """,
            (appellate, original, relation),
        )
        assert _one(cursor) is not None


def test_adjudicative_act_type_unknown_is_null_and_known_values_are_extensible(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions(court_id)
            VALUES (%s) RETURNING act_type_concept_id
            """,
            (court,),
        )
        assert _one(cursor) is None

        custom_code = f"do_act_{uuid4().hex[:8]}"
        cursor.execute(
            "INSERT INTO corpus.adjudicative_act_type_concepts(code,name) "
            "VALUES (%s,'Acto local') RETURNING id",
            (custom_code,),
        )
        custom = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions(court_id,act_type_concept_id)
            VALUES (%s,%s) RETURNING act_type_concept_id
            """,
            (court, custom),
        )
        assert _one(cursor) == custom


def test_judicial_events_use_only_extensible_concept_identity(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        custom_code = f"do_event_{uuid4().hex[:8]}"
        cursor.execute(
            "INSERT INTO corpus.judicial_event_type_concepts(code,name) "
            "VALUES (%s,'Evento local') RETURNING id",
            (custom_code,),
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_status_events(
                case_id,event_type_concept_id,verification_status,verification_method
            ) VALUES (%s,%s,'verified','primary_text')
            RETURNING event_type_concept_id
            """,
            (decision, concept),
        )
        assert _one(cursor) == concept

        cursor.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='decision_legal_status_events'
              AND column_name='status_type'
            """
        )
        assert _one(cursor) == 0


def test_controversy_membership_role_is_an_open_legal_vocabulary(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        custom_code = f"do_family_role_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO corpus.controversy_membership_role_concepts(code,name)
            VALUES (%s,'Rol procesal local') RETURNING id
            """,
            (custom_code,),
        )
        assert _one(cursor) is not None

        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='corpus' AND table_name='controversy_proceedings'
              AND column_name IN ('relation_type','relation_concept_id')
            ORDER BY column_name
            """
        )
        assert [row[0] for row in cursor.fetchall()] == ["relation_concept_id"]


def test_disposition_clause_action_argument_layers_are_canonical_only(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('corpus.disposition_targets')")
        assert _one(cursor) is None
        cursor.execute(
            "SELECT to_regclass('corpus.judicial_disposition_actions') IS NOT NULL"
        )
        assert _one(cursor) is True
        cursor.execute(
            "SELECT to_regclass('corpus.judicial_disposition_action_arguments') IS NOT NULL"
        )
        assert _one(cursor) is True
        cursor.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='disposition_effect_concepts'
              AND column_name='target_type'
            """
        )
        assert _one(cursor) == 0


def test_legacy_legal_mirrors_and_aliases_are_absent(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        legacy_columns = {
            ("judicial_opinions", "opinion_type"),
            ("judicial_vote_stances", "stance_type"),
            ("judicial_authority_assertions", "authority_type"),
            ("decision_legal_status_events", "status_type"),
            ("controversy_proceedings", "relation_type"),
            ("disposition_effect_concepts", "target_type"),
        }
        cursor.execute(
            """
            SELECT table_name,column_name
            FROM information_schema.columns
            WHERE table_schema='corpus'
            """
        )
        existing = {(row[0], row[1]) for row in cursor.fetchall()}
        assert legacy_columns.isdisjoint(existing)

        for legacy_view in (
            "precedential_authority_assertions",
            "claim_effect_concepts",
            "disposition_claim_effects",
            "disposition_targets",
        ):
            cursor.execute("SELECT to_regclass(%s)", (f"corpus.{legacy_view}",))
            assert _one(cursor) is None

        cursor.execute(
            """
            SELECT count(*)
            FROM pg_description d
            JOIN pg_class c ON c.oid=d.objoid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='corpus'
              AND lower(coalesce(d.description,'')) LIKE '%deprecated compatibility%'
            """
        )
        assert _one(cursor) == 0
