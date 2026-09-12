from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
)
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _artifact(*, sha_char: str, object_key: str) -> StoredOfficialArtifact:
    return StoredOfficialArtifact(
        candidate=OfficialDocumentCandidate(
            source="supreme_court",
            source_identifier="fixture-123",
            discovery_url="https://transparencia.poderjudicial.gob.do/consultasSCJ/megaconsulta?fixture=1",
            document_url=(
                "https://transparencia.poderjudicial.gob.do/consultasSCJ/"
                "documentos/pdf/BoletinJudicialIndividual/sentencia-123.pdf"
            ),
        ),
        sha256=sha_char * 64,
        byte_count=1234,
        object_key=object_key,
        already_present=False,
    )


def test_catalog_records_hash_url_filename_storage_and_discovery_trace(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        catalog = PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        )
        artifact = _artifact(
            sha_char="d",
            object_key="official/supreme_court/dd/" + "d" * 64 + ".pdf",
        )

        registered = catalog.register(artifact)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select a.sha256, a.byte_size, r.code,
                       l.source_identifier, l.locator,
                       l.observed_filename, l.discovered_via
                from corpus.source_artifacts a
                join corpus.source_registries r on r.id = %s
                join corpus.source_artifact_locations l on l.artifact_id = a.id
                where a.id = %s and l.locator_type = 'official_url'
                """,
                (registered.source_registry_id, registered.artifact_id),
            )
            row = cursor.fetchone()

        assert row == (
            "d" * 64,
            1234,
            "supreme_court",
            "fixture-123",
            artifact.candidate.document_url,
            "sentencia-123.pdf",
            artifact.candidate.discovery_url,
        )
        assert registered.storage_locator.startswith("s3://jurisnexo-official/")


def test_same_url_can_preserve_two_different_content_hashes(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        catalog = PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        )
        first = _artifact(
            sha_char="e",
            object_key="official/supreme_court/ee/" + "e" * 64 + ".pdf",
        )
        second = _artifact(
            sha_char="f",
            object_key="official/supreme_court/ff/" + "f" * 64 + ".pdf",
        )

        catalog.register(first)
        catalog.register(second)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select a.sha256
                from corpus.source_artifact_locations l
                join corpus.source_artifacts a on a.id = l.artifact_id
                where l.locator_type = 'official_url'
                  and l.locator = %s
                  and a.sha256 in (%s, %s)
                order by a.sha256
                """,
                (first.candidate.document_url, first.sha256, second.sha256),
            )
            hashes = [row[0] for row in cursor.fetchall()]

        assert hashes == [first.sha256, second.sha256]


def test_same_hash_is_deduplicated_but_new_official_location_is_preserved(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        catalog = PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        )
        original = _artifact(
            sha_char="c",
            object_key="official/supreme_court/cc/" + "c" * 64 + ".pdf",
        )
        alternate = StoredOfficialArtifact(
            candidate=OfficialDocumentCandidate(
                source="supreme_court",
                source_identifier="fixture-123-alt",
                discovery_url=original.candidate.discovery_url,
                document_url=(
                    "https://transparencia.poderjudicial.gob.do/consultasSCJ/"
                    "Reportepdf/reporte-fixture-123.pdf"
                ),
            ),
            sha256=original.sha256,
            byte_count=original.byte_count,
            object_key=original.object_key,
            already_present=True,
        )

        first = catalog.register(original)
        second = catalog.register(alternate)

        assert first.artifact_id == second.artifact_id
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select locator
                from corpus.source_artifact_locations
                where artifact_id = %s and locator_type = 'official_url'
                order by locator
                """,
                (first.artifact_id,),
            )
            urls = [row[0] for row in cursor.fetchall()]

        assert urls == sorted(
            [original.candidate.document_url, alternate.candidate.document_url]
        )
