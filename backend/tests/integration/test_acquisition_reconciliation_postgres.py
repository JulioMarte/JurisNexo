from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from jurisnexo.acquisition.completeness import SourceInventorySnapshot
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
    object_key_for,
    sha256_hex,
)
from jurisnexo.acquisition.reconciliation import reconcile_source
from jurisnexo.corpus.artifact_catalog import PostgresOfficialArtifactCatalog
from jurisnexo.corpus.artifact_inventory import PostgresRegisteredArtifactInventory

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


def _empty_keys() -> set[str]:
    return set()


def _empty_requests() -> list[str]:
    return []


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


@dataclass(slots=True)
class MemoryFetcher:
    documents: dict[str, bytes]
    requested: list[str] = field(default_factory=_empty_requests)

    def get_bytes(self, url: str) -> bytes:
        self.requested.append(url)
        return self.documents[url]


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
        assert content_type == "application/pdf"
        assert metadata["sha256"] == sha256_hex(content)
        self.keys.add(key)


def _candidate(identifier: str) -> OfficialDocumentCandidate:
    safe_id = identifier.replace("/", "-")
    return OfficialDocumentCandidate(
        source="constitutional_court",
        source_identifier=identifier,
        discovery_url=f"https://www.tribunalconstitucional.gob.do/fixture/{safe_id}",
        document_url=(
            "https://tribunalsitestorage.blob.core.windows.net/fixture/"
            f"{safe_id}.pdf"
        ),
    )


def test_reconciliation_acquires_only_missing_compendium_rows_and_certifies(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        present = _candidate("TC/0801/26")
        missing = _candidate("TC/0802/26")
        present_content = b"%PDF-1.7 already-present"
        missing_content = b"%PDF-1.7 newly-acquired"
        present_digest = sha256_hex(present_content)
        present_key = object_key_for(source=present.source, sha256=present_digest)

        catalog = PostgresOfficialArtifactCatalog(
            connection=connection,
            storage_bucket="jurisnexo-official",
        )
        catalog.register(
            StoredOfficialArtifact(
                candidate=present,
                sha256=present_digest,
                byte_count=len(present_content),
                object_key=present_key,
                already_present=False,
            )
        )

        store = MemoryObjectStore(keys={present_key})
        fetcher = MemoryFetcher(documents={missing.document_url: missing_content})
        inventory = PostgresRegisteredArtifactInventory(connection=connection)

        result = reconcile_source(
            snapshot=SourceInventorySnapshot(
                source="constitutional_court",
                candidates=(present, missing),
                enumeration_complete=True,
                enumeration_basis="complete integration fixture",
            ),
            inventory=inventory,
            fetcher=fetcher,
            object_store=store,
            artifact_catalog=catalog,
        )

        assert fetcher.requested == [missing.document_url]
        assert result.plan.acquisition_count == 1
        assert result.acquired_count == 1
        assert result.report.complete is True
        assert result.report.discovered_count == 2
        assert result.report.registered_count == 2
        assert result.report.storage_verified_count == 2

        observations = inventory.observations_for("constitutional_court")
        relevant = {
            item.source_identifier: item
            for item in observations
            if item.source_identifier in {present.source_identifier, missing.source_identifier}
        }
        assert set(relevant) == {present.source_identifier, missing.source_identifier}
        assert relevant[missing.source_identifier].sha256 == sha256_hex(missing_content)

        missing_key = object_key_for(
            source=missing.source,
            sha256=sha256_hex(missing_content),
        )
        assert missing_key in store.keys
        assert missing_key.startswith("official/constitutional_court/")
