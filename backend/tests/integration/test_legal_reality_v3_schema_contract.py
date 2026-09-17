from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_legacy_relation_aliases_are_absent(
    connection: psycopg.Connection[Any],
) -> None:
    legacy_relations = {
        "cases",
        "case_dispositions",
        "precedential_authority_assertions",
        "claim_effect_concepts",
        "disposition_claim_effects",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select c.relname
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'corpus'
              and c.relname = any(%s)
            order by c.relname
            """,
            (sorted(legacy_relations),),
        )
        actual = {row[0] for row in cursor.fetchall()}

    assert actual == set(), (
        "Legal Reality V3 requires one canonical physical representation. "
        f"Remove legacy relation aliases instead of restoring compatibility views: {sorted(actual)}"
    )


def test_legacy_scalar_and_text_mirror_columns_are_absent(
    connection: psycopg.Connection[Any],
) -> None:
    forbidden_columns = {
        ("judicial_decisions", "legal_matter_concept_id"),
        ("judicial_decisions", "procedure_concept_id"),
        ("legal_proceedings", "controversy_id"),
        ("judicial_opinions", "author_officer_id"),
        ("judicial_opinions", "opinion_type"),
        ("judicial_vote_stances", "stance_type"),
        ("judicial_authority_assertions", "authority_type"),
        ("decision_legal_status_events", "status_type"),
        ("disposition_targets", "effect_concept_id"),
        ("controversy_proceedings", "relation_type"),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select table_name, column_name
            from information_schema.columns
            where table_schema = 'corpus'
            """
        )
        actual = {
            (table_name, column_name)
            for table_name, column_name in cursor.fetchall()
            if (table_name, column_name) in forbidden_columns
        }

    assert actual == set(), (
        "Do not reintroduce scalar/text mirrors for canonical legal relations or concepts: "
        f"{sorted(actual)}"
    )


def test_canonical_v3_relation_and_concept_columns_exist(
    connection: psycopg.Connection[Any],
) -> None:
    required_columns = {
        ("controversy_proceedings", "relation_concept_id"),
        ("judicial_decisions", "act_type_concept_id"),
        ("judicial_opinions", "opinion_type_concept_id"),
        ("judicial_vote_stances", "stance_concept_id"),
        ("judicial_authority_assertions", "effect_concept_id"),
        ("decision_legal_status_events", "event_type_concept_id"),
        ("judicial_disposition_actions", "effect_concept_id"),
        ("disposition_targets", "action_id"),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select table_name, column_name
            from information_schema.columns
            where table_schema = 'corpus'
            """
        )
        actual = set(cursor.fetchall())

    missing = required_columns - actual
    assert missing == set(), (
        "Canonical Legal Reality V3 columns are part of the persisted model; "
        f"missing: {sorted(missing)}"
    )


def test_removed_legacy_sync_triggers_and_functions_stay_removed(
    connection: psycopg.Connection[Any],
) -> None:
    legacy_triggers = {
        "judicial_decisions_sync_legacy_classification",
        "legal_proceedings_sync_legacy_controversy",
        "judicial_opinions_sync_legacy_author",
        "judicial_opinions_sync_type_concept",
        "judicial_vote_stances_sync_concept",
        "judicial_authority_assertions_sync_effect_concept",
        "decision_legal_status_events_sync_type_concept",
        "disposition_targets_prepare_action",
    }
    legacy_functions = {
        "sync_legacy_decision_classification",
        "sync_legacy_proceeding_controversy",
        "sync_legacy_opinion_author",
        "sync_judicial_opinion_type_concept",
        "sync_judicial_stance_concept",
        "sync_judicial_authority_effect_concept",
        "sync_judicial_event_type_concept",
        "prepare_disposition_target_action",
        "default_adjudicative_act_type",
    }

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select tg.tgname
            from pg_trigger tg
            join pg_class c on c.oid = tg.tgrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'corpus'
              and not tg.tgisinternal
              and tg.tgname = any(%s)
            order by tg.tgname
            """,
            (sorted(legacy_triggers),),
        )
        triggers = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            """
            select p.proname
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'corpus'
              and p.proname = any(%s)
            order by p.proname
            """,
            (sorted(legacy_functions),),
        )
        functions = {row[0] for row in cursor.fetchall()}

    assert triggers == set(), (
        "Removed compatibility triggers must not return; write canonical relations directly: "
        f"{sorted(triggers)}"
    )
    assert functions == set(), (
        "Removed compatibility functions must not return; keep one source of legal truth: "
        f"{sorted(functions)}"
    )


def test_adjudicative_act_type_is_unknown_until_classified(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select is_nullable, column_default
            from information_schema.columns
            where table_schema = 'corpus'
              and table_name = 'judicial_decisions'
              and column_name = 'act_type_concept_id'
            """
        )
        row = cursor.fetchone()

    assert row == ("YES", None), (
        "act_type_concept_id must remain nullable with no fabricated 'decision' default; "
        "NULL means the juridical act form has not yet been classified"
    )
