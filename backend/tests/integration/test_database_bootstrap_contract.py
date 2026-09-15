from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from jurisnexo.modules.legal_reference.bootstrap import (
    apply_database_bootstrap,
    verify_database_bootstrap,
)
from jurisnexo.platform.db.connection import ConnectionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


@pytest.fixture(scope="module")
def connection_factory() -> ConnectionFactory:
    database_url = os.environ["DATABASE_URL"]

    def connect() -> psycopg.Connection[Any]:
        return psycopg.connect(database_url, autocommit=True)

    return connect


@pytest.fixture(scope="module")
def connection(connection_factory: ConnectionFactory) -> Iterator[psycopg.Connection[Any]]:
    with connection_factory() as conn:
        yield conn


def test_bootstrap_contains_independent_scj_and_tc(
    connection_factory: ConnectionFactory,
    connection: psycopg.Connection[Any],
) -> None:
    result = verify_database_bootstrap(connection_factory)
    assert result["bootstrap_version"] == 1
    assert result["courts"] == 2

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT code, judicial_system, court_type
            FROM corpus.courts
            WHERE code IN ('DO-SCJ', 'DO-TC')
            ORDER BY code
            """
        )
        assert cursor.fetchall() == [
            ("DO-SCJ", "ordinary_judiciary", "supreme"),
            ("DO-TC", "constitutional_jurisdiction", "constitutional"),
        ]

        cursor.execute(
            """
            SELECT count(*)
            FROM corpus.court_relations relation
            JOIN corpus.courts source ON source.id = relation.from_court_id
            JOIN corpus.courts target ON target.id = relation.to_court_id
            WHERE source.code IN ('DO-SCJ', 'DO-TC')
              AND target.code IN ('DO-SCJ', 'DO-TC')
            """
        )
        assert cursor.fetchone() == (0,)


def test_bootstrap_is_idempotent(connection_factory: ConnectionFactory) -> None:
    apply_database_bootstrap(connection_factory)
    first = verify_database_bootstrap(connection_factory)
    apply_database_bootstrap(connection_factory)
    second = verify_database_bootstrap(connection_factory)
    assert first == second


def test_scj_organs_and_source_collections_are_bootstrapped(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT co.code
            FROM corpus.court_organs co
            JOIN corpus.courts c ON c.id = co.court_id
            WHERE c.code = 'DO-SCJ'
            ORDER BY co.code
            """
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "PLENO",
            "PRIMERA_SALA",
            "SALAS_REUNIDAS",
            "SEGUNDA_SALA",
            "TERCERA_SALA",
        ]

        cursor.execute(
            """
            SELECT sr.code, sc.code, sc.acquisition_policy, sc.agent_visibility
            FROM corpus.source_collections sc
            JOIN corpus.source_registries sr ON sr.id = sc.source_registry_id
            WHERE sr.code IN ('scj', 'tc')
            ORDER BY sr.code, sc.code
            """
        )
        assert cursor.fetchall() == [
            ("scj", "boletin-judicial", "catalog_only", "hidden"),
            ("scj", "decisiones", "enabled", "hidden"),
            ("scj", "principales-sentencias", "enabled", "hidden"),
            ("scj", "sentencias-historicas", "catalog_only", "hidden"),
            ("tc", "sentencias", "catalog_only", "hidden"),
        ]


def test_lower_and_specialized_courts_fit_without_schema_changes(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.courts (
                code, name, short_name, jurisdiction, judicial_system, court_type
            ) VALUES (
                'DO-TEST-NNA-PI',
                'Tribunal de prueba de Niños, Niñas y Adolescentes',
                'NNA prueba',
                'Distrito Judicial de prueba',
                'ordinary_judiciary',
                'first_instance'
            )
            RETURNING id
            """
        )
        lower_row = cursor.fetchone()
        assert lower_row is not None
        lower_court_id = lower_row[0]

        cursor.execute("SELECT id FROM corpus.courts WHERE code = 'DO-SCJ'")
        scj_row = cursor.fetchone()
        assert scj_row is not None
        scj_id = scj_row[0]

        cursor.execute(
            """
            INSERT INTO corpus.court_jurisdictions (
                court_id, jurisdiction_code, is_primary
            ) VALUES (%s, 'juvenile', true)
            """,
            (lower_court_id,),
        )
        cursor.execute(
            """
            INSERT INTO corpus.court_relations (
                from_court_id, to_court_id, relation_type, source_note
            ) VALUES (%s, %s, 'appeals_to', 'contract test only')
            """,
            (lower_court_id, scj_id),
        )
        cursor.execute(
            """
            INSERT INTO corpus.cases (
                court_id, decision_number, decision_date, decision_date_status, title
            ) VALUES (%s, 'TEST-0001', DATE '2026-09-15', 'verified_official_metadata', 'Caso de prueba')
            RETURNING court_id
            """,
            (lower_court_id,),
        )
        assert cursor.fetchone() == (lower_court_id,)


def test_invalid_court_taxonomy_is_rejected(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO corpus.courts (
                    code, name, jurisdiction, judicial_system, court_type
                ) VALUES (
                    'DO-INVALID-TYPE', 'Tribunal inválido', 'República Dominicana',
                    'ordinary_judiciary', 'invented_level'
                )
                """
            )
