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


def _court(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO corpus.courts(code,name,jurisdiction) VALUES (%s,%s,'DO') RETURNING id",
        (f"DO-ACTION-{suffix}", f"Tribunal action {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _disposition(cursor: psycopg.Cursor[Any], decision_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decision_dispositions(
            case_id,ordinal,raw_text,verification_status
        ) VALUES (%s,1,'FALLA','verified') RETURNING id
        """,
        (decision_id,),
    )
    return _one(cursor)


def _effect(cursor: psycopg.Cursor[Any], target_type: str, code: str) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.disposition_effect_concepts WHERE target_type=%s AND code=%s",
        (target_type, code),
    )
    return _one(cursor)


def _action(cursor: psycopg.Cursor[Any], disposition_id: Any, effect_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.judicial_disposition_actions(
            disposition_id,effect_concept_id,ordinal,
            verification_status,verification_method
        ) VALUES (%s,%s,1,'verified','primary_text') RETURNING id
        """,
        (disposition_id, effect_id),
    )
    return _one(cursor)


def test_action_effect_target_type_must_match_target_row(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        target = _decision(cursor, court)
        disposition = _disposition(cursor, source)
        claim_effect = _effect(cursor, "claim", "denied")
        action = _action(cursor, disposition, claim_effect)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,action_id,target_type,target_decision_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,'decision',%s,'verified','primary_text')
                """,
                (disposition, action, target),
            )


def test_action_effect_cannot_be_changed_to_conflict_with_existing_targets(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        target = _decision(cursor, court)
        disposition = _disposition(cursor, source)
        decision_effect = _effect(cursor, "decision", "reverses")
        claim_effect = _effect(cursor, "claim", "denied")
        action = _action(cursor, disposition, decision_effect)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_targets(
                disposition_id,action_id,target_type,target_decision_id,
                verification_status,verification_method
            ) VALUES (%s,%s,'decision',%s,'verified','primary_text')
            """,
            (disposition, action, target),
        )

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                "UPDATE corpus.judicial_disposition_actions SET effect_concept_id=%s WHERE id=%s",
                (claim_effect, action),
            )


def test_one_action_cannot_repeat_the_same_target(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        target = _decision(cursor, court)
        disposition = _disposition(cursor, source)
        decision_effect = _effect(cursor, "decision", "affirms")
        action = _action(cursor, disposition, decision_effect)
        values = (disposition, action, target)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_targets(
                disposition_id,action_id,target_type,target_decision_id,
                verification_status,verification_method
            ) VALUES (%s,%s,'decision',%s,'verified','primary_text')
            """,
            values,
        )

        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.disposition_targets(
                    disposition_id,action_id,target_type,target_decision_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,'decision',%s,'verified','primary_text')
                """,
                values,
            )
