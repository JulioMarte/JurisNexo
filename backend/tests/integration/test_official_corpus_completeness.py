from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from jurisnexo.acquisition.completeness import SourceInventorySnapshot, verify_source_completeness
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
    object_key_for,
)
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog
from jurisnexo.corpus.artifact_inventory import PostgresRegisteredArtifactInventory

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


def _empty_keys() -> set[str]:
    return set()


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@dataclass(slots=True)
class MemoryObjectStore:
    keys: set[str] = field(default_factory=_empty_keys)

    def exists(self, key: str) -> bool:
        return key in self.keys

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.keys.add(key)


def test_catalog_registration_can_be_certified_end_to_end(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        candidate = OfficialDocumentCandidate(
            source="constitutional_court",
            source_identifier="TC/0999/26",
            discovery_url="https://www.tribunalconstitucional.gob.do/fixture/TC-0999-26",
            document_url="https://tribunalsitestorage.blob.core.windows.net/fixture/TC-0999-26.pdf",
        )
        digest = "9" * 64
        key = object_key_for(source=candidate.source, sha256=digest)
        artifact = StoredOfficialArtifact(
            candidate=candidate,
            sha256=digest,
            byte_count=999,
            object_key=key,
            already_present=False,
        )
        PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        ).register(artifact)

        report = verify_source_completeness(
            snapshot=SourceInventorySnapshot(
                source="constitutional_court",
                candidates=(candidate,),
                enumeration_complete=True,
                enumeration_basis="integration fixture",
            ),
            inventory=PostgresRegisteredArtifactInventory(connection=connection),
            object_store=MemoryObjectStore(keys={key}),
        )

        assert report.complete is True
        assert report.discovered_count == 1
        assert report.registered_count == 1
        assert report.storage_verified_count == 1


def test_historical_url_replacement_certifies_latest_observation(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        candidate = OfficialDocumentCandidate(
            source="constitutional_court",
            source_identifier="TC/0998/26",
            discovery_url="https://www.tribunalconstitucional.gob.do/fixture/TC-0998-26",
            document_url="https://tribunalsitestorage.blob.core.windows.net/fixture/TC-0998-26.pdf",
        )
        catalog = PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        )
        old_digest = "7" * 64
        new_digest = "8" * 64
        catalog.register(
            StoredOfficialArtifact(
                candidate=candidate,
                sha256=old_digest,
                byte_count=700,
                object_key=object_key_for(source=candidate.source, sha256=old_digest),
                already_present=False,
            )
        )
        catalog.register(
            StoredOfficialArtifact(
                candidate=candidate,
                sha256=new_digest,
                byte_count=800,
                object_key=object_key_for(source=candidate.source, sha256=new_digest),
                already_present=False,
            )
        )

        observations = PostgresRegisteredArtifactInventory(
            connection=connection
        ).observations_for("constitutional_court")
        matching = [
            observation
            for observation in observations
            if observation.source_identifier == candidate.source_identifier
        ]

        assert len(matching) == 1
        assert matching[0].sha256 == new_digest

        report = verify_source_completeness(
            snapshot=SourceInventorySnapshot(
                source="constitutional_court",
                candidates=(candidate,),
                enumeration_complete=True,
                enumeration_basis="integration fixture",
            ),
            inventory=PostgresRegisteredArtifactInventory(connection=connection),
            object_store=MemoryObjectStore(
                keys={object_key_for(source=candidate.source, sha256=new_digest)}
            ),
        )
        assert report.complete is True
