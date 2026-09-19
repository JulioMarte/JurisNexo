from __future__ import annotations

from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_v4_superseded_surfaces_are_absent(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        for relation in (
            "corpus.disposition_targets",
            "corpus.disposition_claim_effects",
            "corpus.claim_effect_concepts",
        ):
            cursor.execute("SELECT to_regclass(%s)", (relation,))
            assert _one(cursor) is None

        cursor.execute(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='disposition_effect_concepts'
              AND column_name='target_type'
            """
        )
        assert _one(cursor) == 0


def test_judicial_treatments_use_first_class_legal_issues(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='legal_treatment_assertions'
              AND column_name IN ('legal_issue_id','issue_proposition_id')
            ORDER BY column_name
            """
        )
        assert [row[0] for row in cursor.fetchall()] == ['legal_issue_id']

        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='corpus.legal_treatment_assertions'::regclass
              AND conname='legal_treatment_assertions_context_check'
            """
        )
        definition = _one(cursor)
        assert 'legal_issue_id' in definition
        assert 'issue_proposition_id' not in definition


def test_issue_and_fact_categories_cannot_leak_back_into_legal_propositions(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='corpus.legal_propositions'::regclass
              AND conname='legal_propositions_type_check'
            """
        )
        definition = _one(cursor)
        assert "material_fact" not in definition
        assert "procedural_fact" not in definition
        assert "'issue'" not in definition


def test_new_v4_law_owned_categories_use_shared_concepts(
    connection: psycopg.Connection[Any],
) -> None:
    required_schemes = {
        "legal_issue_relation",
        "factual_proposition_kind",
        "factual_subject_relation",
        "disposition_argument_role",
        "entity_identity_relation",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT code FROM corpus.concept_schemes WHERE code=ANY(%s)",
            (sorted(required_schemes),),
        )
        assert {row[0] for row in cursor.fetchall()} == required_schemes


def test_verified_v4_interpretive_objects_have_evidence_guards(
    connection: psycopg.Connection[Any],
) -> None:
    expected_triggers = {
        "legal_issues_verified_require_evidence",
        "factual_propositions_verified_require_evidence",
        "entity_identity_verified_require_evidence",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tg.tgname
            FROM pg_trigger tg
            JOIN pg_class c ON c.oid=tg.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='corpus'
              AND NOT tg.tgisinternal
              AND tg.tgname=ANY(%s)
            """,
            (sorted(expected_triggers),),
        )
        assert {row[0] for row in cursor.fetchall()} == expected_triggers
