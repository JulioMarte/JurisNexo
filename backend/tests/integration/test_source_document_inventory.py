from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from jurisnexo.corpus.source_inventory import (
    PostgresSourceDocumentInventory,
    SourceDocumentObservation,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_observe_many_is_idempotent_for_available_and_metadata_only_records(
    connection: psycopg.Connection[Any],
) -> None:
    available = SourceDocumentObservation(
        source="supreme_court",
        source_identifier="batch-fixture-available",
        source_collection="decisions",
        document_kind="judicial_decision",
        discovery_url="https://consultasentenciascj.poderjudicial.gob.do/",
        document_url="https://consultaglobal.blob.core.windows.net/fixture/available.pdf",
        artifact_availability="available",
        source_payload={"fixture": "available"},
    )
    metadata_only = SourceDocumentObservation(
        source="supreme_court",
        source_identifier="batch-fixture-metadata-only",
        source_collection="bulletins",
        document_kind="official_bulletin",
        discovery_url="https://consultasentenciascj.poderjudicial.gob.do/",
        document_url=None,
        artifact_availability="not_published",
        source_payload={"fixture": "metadata-only"},
        normalization_notes={"document_url_state": "source_null"},
    )

    with connection.transaction(force_rollback=True):
        inventory = PostgresSourceDocumentInventory(connection=connection)
        assert inventory.observe_many([available, metadata_only]) == 2
        assert inventory.observe_many([available, metadata_only]) == 2

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM corpus.source_documents sd
                JOIN corpus.source_registries sr ON sr.id = sd.source_registry_id
                WHERE sr.code = 'supreme_court'
                  AND sd.source_identifier LIKE 'batch-fixture-%%'
                """
            )
            document_count = cursor.fetchone()
            cursor.execute(
                """
                SELECT count(*)
                FROM corpus.source_document_observations sdo
                JOIN corpus.source_documents sd ON sd.id = sdo.source_document_id
                JOIN corpus.source_registries sr ON sr.id = sd.source_registry_id
                WHERE sr.code = 'supreme_court'
                  AND sd.source_identifier LIKE 'batch-fixture-%%'
                """
            )
            observation_count = cursor.fetchone()

        assert document_count == (2,)
        assert observation_count == (2,)


def test_observe_many_rejects_duplicate_batch_identity(
    connection: psycopg.Connection[Any],
) -> None:
    observation = SourceDocumentObservation(
        source="supreme_court",
        source_identifier="batch-duplicate",
        source_collection="decisions",
        document_kind="judicial_decision",
        discovery_url="https://consultasentenciascj.poderjudicial.gob.do/",
        document_url="https://consultaglobal.blob.core.windows.net/fixture/duplicate.pdf",
        artifact_availability="available",
        source_payload={"fixture": "duplicate"},
    )
    inventory = PostgresSourceDocumentInventory(connection=connection)
    with pytest.raises(ValueError, match="duplicate source document identities"):
        inventory.observe_many([observation, observation])
