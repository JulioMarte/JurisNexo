from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from psycopg import Connection

from jurisnexo.corpus.artifact_catalog import SOURCE_REGISTRIES

ArtifactAvailability = Literal["available", "not_published", "unavailable", "unknown"]
SourceCode = Literal["supreme_court", "constitutional_court"]
JsonObject = dict[str, Any]


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class SourceDocumentObservation:
    source: SourceCode
    source_identifier: str
    source_collection: str
    document_kind: str
    discovery_url: str
    document_url: str | None
    artifact_availability: ArtifactAvailability
    source_payload: JsonObject
    normalization_notes: JsonObject = field(default_factory=_empty_json_object)

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
) -> tuple[str | None, ArtifactAvailability, JsonObject]:
    """Normalize only SCJ bulletin URL defects proven by live source evidence."""
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
        return raw[4:], "available", {
            "document_url_normalization": "stripped_literal_NULL_prefix",
            "raw_document_url": raw,
        }
    raise ValueError(f"unsupported SCJ bulletin document URL shape: {raw!r}")


def scj_source_observation_from_record(
    *, record: JsonObject, discovery_url: str
) -> SourceDocumentObservation:
    row_value = record.get("row")
    if not isinstance(row_value, dict):
        raise TypeError("SCJ inventory record is missing its row object")
    row = cast(JsonObject, row_value)
    surface = str(record.get("surface") or "").strip()
    record_notes = record.get("_normalization_notes")
    notes: JsonObject = dict(cast(JsonObject, record_notes)) if isinstance(record_notes, dict) else {}
    if surface == "decisions":
        expediente_id = str(row.get("idExpediente") or "").strip()
        guid_blob = str(row.get("guidBlob") or "").strip()
        if not expediente_id:
            raise ValueError("SCJ decision lacks idExpediente")
        source_identifier = f"expediente:{expediente_id}"
        if guid_blob:
            source_identifier += f":{guid_blob}"
        collection = "decisions"
        document_kind = "judicial_decision"
        document_url = str(row.get("urlBlob") or "").strip()
        if not document_url.startswith("https://"):
            raise ValueError("SCJ decision lacks HTTPS document URL")
        availability: ArtifactAvailability = "available"
    elif surface == "historical":
        year = str(row.get("ano") or "").strip()
        month = str(row.get("mes") or "").strip()
        parties = " ".join(str(row.get("partes") or "").split())
        document_url = str(row.get("rutaDoc") or "").strip()
        if not (year or month or parties):
            raise ValueError("SCJ historical decision lacks descriptive source metadata")
        if not document_url.startswith("https://"):
            raise ValueError("SCJ historical decision lacks HTTPS document URL")
        # The historical endpoint exposes no publisher-issued row/document id. Year/month/parties
        # is demonstrably non-unique in the live corpus, so the official document locator is the
        # only collision-safe deterministic source identity we can prove without inventing
        # semantic continuity. If the publisher later changes the locator, that is retained as a
        # new source record until a separate resolution layer proves equivalence.
        url_digest = hashlib.sha256(document_url.encode("utf-8")).hexdigest()
        source_identifier = f"historical-url-sha256:{url_digest}"
        notes["source_identifier_basis"] = "official_document_url_sha256"
        collection = "historical-decisions"
        document_kind = "judicial_decision"
        availability = "available"
    elif surface == "bulletins":
        body_id = str(row.get("idCuerpo") or "").strip()
        header_id = str(row.get("idCabecera") or "").strip()
        if not body_id:
            raise ValueError("SCJ bulletin lacks idCuerpo")
        source_identifier = f"bulletin:{header_id}:{body_id}"
        collection = "bulletins"
        document_kind = "official_bulletin"
        document_url, availability, url_notes = normalize_scj_bulletin_pdf_url(
            row.get("urlCuerpo")
        )
        notes.update(url_notes)
    else:
        raise ValueError(f"unsupported SCJ inventory surface: {surface!r}")
    return SourceDocumentObservation(
        source="supreme_court",
        source_identifier=source_identifier,
        source_collection=collection,
        document_kind=document_kind,
        discovery_url=discovery_url,
        document_url=document_url,
        artifact_availability=availability,
        source_payload=row,
        normalization_notes=notes,
    )


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
                ) VALUES (%s, %s, %s, 'official_primary', %s)
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
                    definition.name,
                    definition.institution,
                    definition.base_locator,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"failed to resolve source registry {source}")
        return str(row[0])

    def observe(self, observation: SourceDocumentObservation) -> str:
        registry_id = self._ensure_registry(observation.source)
        payload_sha256 = observation.payload_sha256
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.source_documents (
                    source_registry_id, source_identifier, source_collection,
                    document_kind, discovery_url, current_document_url,
                    artifact_availability, latest_source_metadata, latest_payload_sha256
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (source_registry_id, source_collection, source_identifier)
                DO UPDATE SET
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
                    json.dumps(
                        observation.source_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
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
                    source_document_id, discovery_url, document_url,
                    artifact_availability, source_payload, payload_sha256,
                    normalization_notes
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    source_document_id,
                    observation.discovery_url,
                    observation.document_url,
                    observation.artifact_availability,
                    json.dumps(
                        observation.source_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    payload_sha256,
                    json.dumps(
                        observation.normalization_notes,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
        return source_document_id

    def link_artifact_sha256(
        self,
        *,
        source_document_id: str,
        sha256: str,
        relationship_type: str = "primary",
    ) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM corpus.source_artifacts WHERE sha256 = %s",
                (sha256,),
            )
            row = cursor.fetchone()
            if row is None:
                raise LookupError(f"artifact not registered for sha256={sha256}")
            cursor.execute(
                """
                INSERT INTO corpus.source_document_artifacts (
                    source_document_id, artifact_id, relationship_type
                ) VALUES (%s, %s, %s)
                ON CONFLICT (source_document_id, artifact_id, relationship_type)
                DO UPDATE SET last_seen_at = clock_timestamp()
                """,
                (source_document_id, str(row[0]), relationship_type),
            )
