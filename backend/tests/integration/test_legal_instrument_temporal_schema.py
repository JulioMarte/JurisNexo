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
    pytest.mark.provenance,
]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _instrument(cursor: psycopg.Cursor[Any], title: str, instrument_type: str = "statute") -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_instruments (
            instrument_type, canonical_title, identity_status
        ) VALUES (%s, %s, 'canonical')
        RETURNING id
        """,
        (instrument_type, title),
    )
    return _one(cursor)


def _version(
    cursor: psycopg.Cursor[Any],
    instrument_id: Any,
    *,
    kind: str,
    valid_from: str,
    derived_from: Any | None = None,
) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_instrument_versions (
            instrument_id, version_kind, valid_from, version_status,
            derivation_method, derived_from_version_id
        ) VALUES (%s, %s, %s, 'verified', 'official_primary_text', %s)
        RETURNING id
        """,
        (instrument_id, kind, valid_from, derived_from),
    )
    return _one(cursor)


def _provision(cursor: psycopg.Cursor[Any], instrument_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_provisions (instrument_id, identity_status)
        VALUES (%s, 'canonical')
        RETURNING id
        """,
        (instrument_id,),
    )
    return _one(cursor)


def test_same_provision_identity_can_have_multiple_temporal_texts(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_id = _instrument(cursor, "Ley temporal de prueba")
        original = _version(cursor, instrument_id, kind="original", valid_from="2020-01-01")
        amended = _version(
            cursor,
            instrument_id,
            kind="amended",
            valid_from="2022-04-01",
            derived_from=original,
        )
        provision_id = _provision(cursor, instrument_id)

        cursor.execute(
            """
            INSERT INTO corpus.legal_provision_versions (
                instrument_id, instrument_version_id, provision_id,
                provision_type, label, normalized_label, text, content_status
            ) VALUES
                (%s, %s, %s, 'article', 'Artículo 7', 'articulo-7',
                 'Texto vigente desde 2020.', 'verified'),
                (%s, %s, %s, 'article', 'Artículo 7', 'articulo-7',
                 'Texto reformado vigente desde 2022.', 'verified')
            """,
            (
                instrument_id,
                original,
                provision_id,
                instrument_id,
                amended,
                provision_id,
            ),
        )

        cursor.execute(
            """
            SELECT instrument_version_id, provision_id, text
            FROM corpus.legal_provision_versions
            WHERE provision_id = %s
            ORDER BY created_at, id
            """,
            (provision_id,),
        )
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert {row[1] for row in rows} == {provision_id}
        assert {row[2] for row in rows} == {
            "Texto vigente desde 2020.",
            "Texto reformado vigente desde 2022.",
        }


def test_provision_label_and_parent_belong_to_version_not_stable_identity(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_id = _instrument(cursor, "Código renumerable de prueba", "code")
        first = _version(cursor, instrument_id, kind="original", valid_from="2019-01-01")
        second = _version(
            cursor,
            instrument_id,
            kind="amended",
            valid_from="2023-01-01",
            derived_from=first,
        )
        chapter_a = _provision(cursor, instrument_id)
        chapter_b = _provision(cursor, instrument_id)
        article = _provision(cursor, instrument_id)

        cursor.execute(
            """
            INSERT INTO corpus.legal_provision_versions (
                instrument_id, instrument_version_id, provision_id,
                provision_type, label, normalized_label, ordinal, content_status
            ) VALUES
                (%s, %s, %s, 'chapter', 'Capítulo I', 'capitulo-i', 1, 'verified'),
                (%s, %s, %s, 'chapter', 'Capítulo II', 'capitulo-ii', 2, 'verified'),
                (%s, %s, %s, 'chapter', 'Capítulo I', 'capitulo-i', 1, 'verified'),
                (%s, %s, %s, 'chapter', 'Capítulo II', 'capitulo-ii', 2, 'verified')
            """,
            (
                instrument_id,
                first,
                chapter_a,
                instrument_id,
                first,
                chapter_b,
                instrument_id,
                second,
                chapter_a,
                instrument_id,
                second,
                chapter_b,
            ),
        )
        cursor.execute(
            """
            INSERT INTO corpus.legal_provision_versions (
                instrument_id, instrument_version_id, provision_id,
                parent_provision_id, provision_type, label,
                normalized_label, text, content_status
            ) VALUES
                (%s, %s, %s, %s, 'article', 'Artículo 10', 'articulo-10',
                 'Texto original.', 'verified'),
                (%s, %s, %s, %s, 'article', 'Artículo 11', 'articulo-11',
                 'Mismo artículo, renumerado y reubicado.', 'verified')
            """,
            (
                instrument_id,
                first,
                article,
                chapter_a,
                instrument_id,
                second,
                article,
                chapter_b,
            ),
        )

        cursor.execute(
            """
            SELECT label, parent_provision_id
            FROM corpus.legal_provision_versions
            WHERE provision_id = %s
            ORDER BY label
            """,
            (article,),
        )
        assert set(cursor.fetchall()) == {
            ("Artículo 10", chapter_a),
            ("Artículo 11", chapter_b),
        }


def test_version_cannot_use_provision_from_another_instrument(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_a = _instrument(cursor, "Ley A")
        instrument_b = _instrument(cursor, "Ley B")
        version_a = _version(cursor, instrument_a, kind="original", valid_from="2020-01-01")
        provision_b = _provision(cursor, instrument_b)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_provision_versions (
                    instrument_id, instrument_version_id, provision_id,
                    provision_type, label, normalized_label, content_status
                ) VALUES (%s, %s, %s, 'article', 'Artículo 1', 'articulo-1', 'verified')
                """,
                (instrument_a, version_a, provision_b),
            )


def test_derived_version_must_belong_to_same_instrument(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_a = _instrument(cursor, "Ley derivada A")
        instrument_b = _instrument(cursor, "Ley derivada B")
        version_b = _version(cursor, instrument_b, kind="original", valid_from="2020-01-01")

        with connection.transaction(), pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_instrument_versions (
                    instrument_id, version_kind, valid_from, version_status,
                    derivation_method, derived_from_version_id
                ) VALUES (%s, 'amended', '2024-01-01', 'verified',
                          'official_primary_text', %s)
                """,
                (instrument_a, version_b),
            )


def test_amending_law_remains_distinct_instrument_with_explicit_effect(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        target = _instrument(cursor, "Ley 100-20")
        target_provision = _provision(cursor, target)
        amendment = _instrument(cursor, "Ley 25-22")
        amendment_version = _version(
            cursor,
            amendment,
            kind="original",
            valid_from="2022-04-01",
        )

        cursor.execute(
            """
            INSERT INTO corpus.legal_amendment_effects (
                source_instrument_id, source_version_id,
                target_instrument_id, target_provision_id,
                effect_type, effective_on, raw_effect_text,
                verification_status, verification_method
            ) VALUES (
                %s, %s, %s, %s, 'replaces', '2022-04-01',
                'Se modifica el artículo 7 para que diga...',
                'verified', 'explicit_primary_text'
            )
            RETURNING source_instrument_id, target_instrument_id, target_provision_id
            """,
            (amendment, amendment_version, target, target_provision),
        )
        assert cursor.fetchone() == (amendment, target, target_provision)
        assert amendment != target


def test_verified_lifecycle_date_cannot_be_invented(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_id = _instrument(cursor, "Ley con fecha desconocida")

        with connection.transaction(), pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_instrument_events (
                    instrument_id, event_type, occurred_on, date_status,
                    verification_status, verification_method
                ) VALUES (
                    %s, 'published', NULL, 'verified_official_metadata',
                    'verified', 'official_metadata'
                )
                """,
                (instrument_id,),
            )

        cursor.execute(
            """
            INSERT INTO corpus.legal_instrument_events (
                instrument_id, event_type, occurred_on, date_status,
                raw_description, verification_status, verification_method
            ) VALUES (
                %s, 'published', NULL, 'unknown',
                'La publicación consta, pero la fecha no pudo verificarse.',
                'candidate', 'source_observation'
            )
            RETURNING occurred_on, date_status
            """,
            (instrument_id,),
        )
        assert cursor.fetchone() == (None, "unknown")


def test_source_document_mapping_preserves_scope_boundary(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_id = _instrument(cursor, "Ley pública")
        version_id = _version(cursor, instrument_id, kind="original", valid_from="2020-01-01")

        cursor.execute(
            """
            INSERT INTO corpus.scopes (visibility, organization_id)
            VALUES ('private', %s)
            RETURNING id
            """,
            (uuid4(),),
        )
        private_scope = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_documents (
                scope_id, document_type, title, identity_status
            ) VALUES (%s, 'statute', 'Texto privado', 'canonical')
            RETURNING id
            """,
            (private_scope,),
        )
        private_document = _one(cursor)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_instrument_version_documents (
                    instrument_version_id, document_id, document_role,
                    verification_status, verification_method
                ) VALUES (%s, %s, 'official_text', 'verified', 'contract_test')
                """,
                (version_id, private_document),
            )


def test_repeated_child_labels_are_scoped_to_parent_within_version(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument_id = _instrument(cursor, "Ley de estructura temporal")
        version_id = _version(cursor, instrument_id, kind="original", valid_from="2020-01-01")
        article_10 = _provision(cursor, instrument_id)
        article_11 = _provision(cursor, instrument_id)
        paragraph_a = _provision(cursor, instrument_id)
        paragraph_b = _provision(cursor, instrument_id)
        paragraph_duplicate = _provision(cursor, instrument_id)

        cursor.execute(
            """
            INSERT INTO corpus.legal_provision_versions (
                instrument_id, instrument_version_id, provision_id,
                provision_type, label, normalized_label, content_status
            ) VALUES
                (%s, %s, %s, 'article', 'Artículo 10', 'articulo-10', 'verified'),
                (%s, %s, %s, 'article', 'Artículo 11', 'articulo-11', 'verified')
            """,
            (
                instrument_id,
                version_id,
                article_10,
                instrument_id,
                version_id,
                article_11,
            ),
        )
        for parent, provision in ((article_10, paragraph_a), (article_11, paragraph_b)):
            cursor.execute(
                """
                INSERT INTO corpus.legal_provision_versions (
                    instrument_id, instrument_version_id, provision_id,
                    parent_provision_id, provision_type, label,
                    normalized_label, content_status
                ) VALUES (
                    %s, %s, %s, %s, 'paragraph', 'Párrafo I', 'parrafo-i', 'verified'
                )
                """,
                (instrument_id, version_id, provision, parent),
            )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                INSERT INTO corpus.legal_provision_versions (
                    instrument_id, instrument_version_id, provision_id,
                    parent_provision_id, provision_type, label,
                    normalized_label, content_status
                ) VALUES (
                    %s, %s, %s, %s, 'paragraph', 'Párrafo I', 'parrafo-i', 'verified'
                )
                """,
                (
                    instrument_id,
                    version_id,
                    paragraph_duplicate,
                    article_10,
                ),
            )
