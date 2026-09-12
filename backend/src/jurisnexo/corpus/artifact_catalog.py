from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

import psycopg

from jurisnexo.acquisition.official_corpus import (
    SCJ_MEGAQUERY_URL,
    TC_SENTENCES_URL,
    SourceName,
    StoredOfficialArtifact,
)


@dataclass(frozen=True, slots=True)
class SourceRegistryDefinition:
    code: SourceName
    name: str
    institution: str
    base_locator: str


SOURCE_REGISTRIES: dict[SourceName, SourceRegistryDefinition] = {
    "supreme_court": SourceRegistryDefinition(
        code="supreme_court",
        name="Suprema Corte de Justicia",
        institution="Poder Judicial de la República Dominicana",
        base_locator=SCJ_MEGAQUERY_URL,
    ),
    "constitutional_court": SourceRegistryDefinition(
        code="constitutional_court",
        name="Tribunal Constitucional",
        institution="Tribunal Constitucional de la República Dominicana",
        base_locator=TC_SENTENCES_URL,
    ),
}


@dataclass(frozen=True, slots=True)
class ArtifactCatalogRecord:
    artifact_id: UUID
    source_registry_id: UUID
    official_url: str
    source_identifier: str
    observed_filename: str | None
    storage_locator: str


def observed_filename_from_url(url: str) -> str | None:
    name = PurePosixPath(unquote(urlparse(url).path)).name.strip()
    return name or None


@dataclass(slots=True)
class PostgresOfficialArtifactCatalog:
    """Durable bibliography/provenance ledger for official acquired artifacts."""

    connection: psycopg.Connection[Any]
    storage_bucket: str

    def __post_init__(self) -> None:
        if not self.storage_bucket.strip():
            raise ValueError("storage_bucket must not be empty")

    def storage_locator(self, object_key: str) -> str:
        return f"s3://{self.storage_bucket}/{object_key}"

    def register(self, artifact: StoredOfficialArtifact) -> ArtifactCatalogRecord:
        definition = SOURCE_REGISTRIES[artifact.candidate.source]
        observed_filename = observed_filename_from_url(artifact.candidate.document_url)
        storage_locator = self.storage_locator(artifact.object_key)

        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.source_registries (
                    code, name, institution, authority_class, base_locator
                )
                values (%s, %s, %s, 'official_primary', %s)
                on conflict (code) do update
                set name = excluded.name,
                    institution = excluded.institution,
                    base_locator = excluded.base_locator,
                    active = true,
                    updated_at = now()
                returning id
                """,
                (
                    definition.code,
                    definition.name,
                    definition.institution,
                    definition.base_locator,
                ),
            )
            registry_row = cursor.fetchone()
            if registry_row is None:
                raise RuntimeError("source registry upsert did not return an identifier")
            source_registry_id: UUID = registry_row[0]

            cursor.execute(
                """
                insert into corpus.source_artifacts (
                    source_registry_id, sha256, mime_type, byte_size
                )
                values (%s, %s, 'application/pdf', %s)
                on conflict (sha256) do update
                set source_registry_id = coalesce(
                    corpus.source_artifacts.source_registry_id,
                    excluded.source_registry_id
                )
                returning id
                """,
                (source_registry_id, artifact.sha256, artifact.byte_count),
            )
            artifact_row = cursor.fetchone()
            if artifact_row is None:
                raise RuntimeError("source artifact upsert did not return an identifier")
            artifact_id: UUID = artifact_row[0]

            self._upsert_location(
                cursor,
                artifact_id=artifact_id,
                source_registry_id=source_registry_id,
                source_identifier=artifact.candidate.source_identifier,
                locator_type="official_url",
                locator=artifact.candidate.document_url,
                observed_filename=observed_filename,
                discovered_via=artifact.candidate.discovery_url,
                is_preferred=False,
            )
            self._upsert_location(
                cursor,
                artifact_id=artifact_id,
                source_registry_id=source_registry_id,
                source_identifier=artifact.candidate.source_identifier,
                locator_type="storage_object",
                locator=storage_locator,
                observed_filename=PurePosixPath(artifact.object_key).name,
                discovered_via=artifact.candidate.document_url,
                is_preferred=True,
            )

        return ArtifactCatalogRecord(
            artifact_id=artifact_id,
            source_registry_id=source_registry_id,
            official_url=artifact.candidate.document_url,
            source_identifier=artifact.candidate.source_identifier,
            observed_filename=observed_filename,
            storage_locator=storage_locator,
        )

    @staticmethod
    def _upsert_location(
        cursor: psycopg.Cursor[Any],
        *,
        artifact_id: UUID,
        source_registry_id: UUID,
        source_identifier: str,
        locator_type: str,
        locator: str,
        observed_filename: str | None,
        discovered_via: str,
        is_preferred: bool,
    ) -> None:
        cursor.execute(
            """
            insert into corpus.source_artifact_locations (
                artifact_id,
                source_registry_id,
                source_identifier,
                locator_type,
                locator,
                observed_filename,
                discovered_via,
                is_preferred,
                first_seen_at,
                last_seen_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp(), clock_timestamp())
            on conflict (artifact_id, locator_type, locator) do update
            set source_registry_id = excluded.source_registry_id,
                source_identifier = excluded.source_identifier,
                observed_filename = coalesce(
                    excluded.observed_filename,
                    corpus.source_artifact_locations.observed_filename
                ),
                discovered_via = excluded.discovered_via,
                is_preferred = excluded.is_preferred,
                last_seen_at = clock_timestamp()
            """,
            (
                artifact_id,
                source_registry_id,
                source_identifier,
                locator_type,
                locator,
                observed_filename,
                discovered_via,
                is_preferred,
            ),
        )
