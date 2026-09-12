from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from psycopg import Connection

from jurisnexo.corpus.artifact_catalog import SOURCE_REGISTRIES

ArtifactAvailability = Literal["available", "not_published", "unavailable", "unknown"]
SourceCode = Literal["supreme_court", "constitutional_court"]


@dataclass(frozen=True, slots=True)
class SourceDocumentObservation:
    source: SourceCode
    source_identifier: str
    source_collection: str
    document_kind: str
    discovery_url: str
    document_url: str | None
    artifact_availability: ArtifactAvailability
    source_payload: dict[str, Any]
    normalization_notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_identifier.strip():
            raise ValueError("source_identifier must not be empty")
        if not self.source_collection.strip():
            raise ValueError("source_collection must not be empty")
        if not self.document_kind.strip():
            raise ValueError("document_kind must not be empty")
        if not self.discovery_url.startswith("https://"):
            raise ValueError("discovery_url must use HTTPS")
        if self.document_url is not None and not self.document_url.startswith("https://"):
            raise ValueError("document_url must use HTTPS when present")
        if self.artifact_availability == "available" and self.document_url is None:
            raise ValueError("available source documents require document_url")

    @property
    def payload_sha256(self) -> str:
        canonical = json.dumps(
            self.source_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def normalize_scj_bulletin_pdf_url(
    raw_value: object,
) -> tuple[str | None, ArtifactAvailability, dict[str, Any]]:
    """Normalize only SCJ bulletin URL defects proven by live source evidence.

    The SCJ currently contains historical rows whose `urlCuerpo` is prefixed by
    the literal string `NULL` immediately before an otherwise valid HTTPS URL.
    We repair exactly that source defect and preserve the raw value in notes.
    Missing URLs remain explicit metadata-only source records rather than being
    invented or silently dropped.
    """

    if raw_value is None:
        return None, "not_published", {"document_url_state": "source_null"}
    raw = str(raw_value).strip()
    if not raw or raw.casefold() == "null":
        return None, "not_published", {
            "document_url_state": "source_null_text",
            "raw_document_url": raw,
        }
    if raw.startswith("https://"):
        return raw, "available", {}
    if raw.startswith("NULLhttps://"):
        normalized = raw[4:]
        return normalized, "available", {
            "document_url_normalization": "stripped_literal_NULL_prefix",
            "raw_document_url": raw,
        }
    raise ValueError(f"unsupported SCJ bulletin document URL shape: {raw!r}")


@dataclass(slots=True)
class PostgresSourceDocumentInventory:
    connection: Connection[Any]

    def _ensure_registry(self, source: SourceCode) -> str:
        definition = SOURCE_REGISTRIES[source]
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.source_registries (
                    code, name, institution, authority_class, base_locator
                )
                VALUES (%s, %s, %s, 'official_primary', %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    institution = EXCLUDED.institution,
                    base_locator = EXCLUDED.base_locator,
                    active = true,
                    updated_at = now()
                RETURNING id
                """,
                (
                    source,
                    definition["name"],
                    definition["institution"],
                    definition["base_locator"],
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"failed to resolve source registry {source}")
        return str(row[0])

    def observe(self, observation: SourceDocumentObservation) -> str:
        registry_id = self._ensure_registry(observation.source)
        payload_sha256 = observation.payload_sha256
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO corpus.source_documents (
                        source_registry_id,
                        source_identifier,
                        source_collection,
                        document_kind,
                        discovery_url,
                        current_document_url,
                        artifact_availability,
                        latest_source_metadata,
                        latest_payload_sha256
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (
                        source_registry_id, source_collection, source_identifier
                    ) DO UPDATE SET
                        document_kind = EXCLUDED.document_kind,
                        discovery_url = EXCLUDED.discovery_url,
                        current_document_url = EXCLUDED.current_document_url,
                        artifact_availability = EXCLUDED.artifact_availability,
                        latest_source_metadata = EXCLUDED.latest_source_metadata,
                        latest_payload_sha256 = EXCLUDED.latest_payload_sha256,
                        last_seen_at = clock_timestamp(),
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        registry_id,
                        observation.source_identifier,
                        observation.source_collection,
                        observation.document_kind,
                        observation.discovery_url,
                        observation.document_url,
                        observation.artifact_availability,
                        json.dumps(observation.source_payload, ensure_ascii=False, sort_keys=True),
                        payload_sha256,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("failed to persist source document")
                source_document_id = str(row[0])
                cursor.execute(
                    """
                    INSERT INTO corpus.source_document_observations (
                        source_document_id,
                        discovery_url,
                        document_url,
                        artifact_availability,
                        source_payload,
                        payload_sha256,
                        normalization_notes
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        source_document_id,
                        observation.discovery_url,
                        observation.document_url,
                        observation.artifact_availability,
                        json.dumps(observation.source_payload, ensure_ascii=False, sort_keys=True),
                        payload_sha256,
                        json.dumps(observation.normalization_notes, ensure_ascii=False, sort_keys=True),
                    ),
                )
        return source_document_id
