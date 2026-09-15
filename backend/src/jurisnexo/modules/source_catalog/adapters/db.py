from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from jurisnexo.modules.source_catalog.contracts import (
    SourceCollectionRecord,
    SourceDocumentRecord,
    SourceRecord,
)
from jurisnexo.platform.db.connection import ConnectionFactory


class PostgresSourceCatalog:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def list_sources(
        self, *, after_id: UUID | None, limit: int
    ) -> tuple[SourceRecord, ...]:
        with self._connection_factory() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, code, name, institution, authority_class, base_locator,
                       active, created_at, updated_at
                FROM corpus.source_registries
                WHERE (%s::uuid IS NULL OR id > %s::uuid)
                ORDER BY id
                LIMIT %s
                """,
                (after_id, after_id, limit),
            )
            return tuple(self._source(row) for row in cursor.fetchall())

    def create_source(
        self,
        *,
        code: str,
        name: str,
        institution: str,
        authority_class: str,
        base_locator: str | None,
        active: bool,
    ) -> SourceRecord:
        try:
            with self._connection_factory() as connection, connection.transaction(), connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    INSERT INTO corpus.source_registries (
                        code, name, institution, authority_class, base_locator, active
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, code, name, institution, authority_class, base_locator,
                              active, created_at, updated_at
                    """,
                    (code, name, institution, authority_class, base_locator, active),
                )
                row = cursor.fetchone()
        except UniqueViolation as exc:
            raise ValueError("source_code_exists") from exc
        if row is None:
            raise RuntimeError("source insert returned no row")
        return self._source(row)

    def set_source_active(self, *, source_id: UUID, active: bool) -> SourceRecord:
        with self._connection_factory() as connection, connection.transaction(), connection.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute(
                """
                UPDATE corpus.source_registries
                SET active = %s, updated_at = now()
                WHERE id = %s
                RETURNING id, code, name, institution, authority_class, base_locator,
                          active, created_at, updated_at
                """,
                (active, source_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise LookupError("source_not_found")
        return self._source(row)

    def list_collections(
        self,
        *,
        source_id: UUID | None,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[SourceCollectionRecord, ...]:
        with self._connection_factory() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT sc.id, sc.source_registry_id, sr.code AS source_code,
                       sc.code, sc.document_kind, sc.acquisition_policy,
                       sc.agent_visibility, sc.active, sc.revision,
                       sc.created_at, sc.updated_at
                FROM corpus.source_collections sc
                JOIN corpus.source_registries sr ON sr.id = sc.source_registry_id
                WHERE (%s::uuid IS NULL OR sc.source_registry_id = %s::uuid)
                  AND (%s::uuid IS NULL OR sc.id > %s::uuid)
                ORDER BY sc.id
                LIMIT %s
                """,
                (source_id, source_id, after_id, after_id, limit),
            )
            return tuple(self._collection(row) for row in cursor.fetchall())

    def create_collection(
        self,
        *,
        source_id: UUID,
        code: str,
        document_kind: str,
        acquisition_policy: str,
        agent_visibility: str,
        active: bool,
    ) -> SourceCollectionRecord:
        try:
            with self._connection_factory() as connection, connection.transaction(), connection.cursor(
                row_factory=dict_row
            ) as cursor:
                cursor.execute(
                    """
                    INSERT INTO corpus.source_collections (
                        source_registry_id, code, document_kind,
                        acquisition_policy, agent_visibility, active
                    )
                    SELECT id, %s, %s, %s, %s, %s
                    FROM corpus.source_registries
                    WHERE id = %s
                    RETURNING id, source_registry_id, code, document_kind,
                              acquisition_policy, agent_visibility, active,
                              revision, created_at, updated_at
                    """,
                    (
                        code,
                        document_kind,
                        acquisition_policy,
                        agent_visibility,
                        active,
                        source_id,
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    row["source_code"] = self._source_code(cursor, source_id)
        except UniqueViolation as exc:
            raise ValueError("source_collection_exists") from exc
        if row is None:
            raise LookupError("source_not_found")
        return self._collection(row)

    def set_collection_policy(
        self,
        *,
        collection_id: UUID,
        acquisition_policy: str,
        agent_visibility: str,
        active: bool,
        expected_revision: int,
    ) -> SourceCollectionRecord:
        with self._connection_factory() as connection, connection.transaction(), connection.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute(
                """
                UPDATE corpus.source_collections
                SET acquisition_policy = %s,
                    agent_visibility = %s,
                    active = %s,
                    revision = revision + 1,
                    updated_at = now()
                WHERE id = %s AND revision = %s
                RETURNING id, source_registry_id, code, document_kind,
                          acquisition_policy, agent_visibility, active,
                          revision, created_at, updated_at
                """,
                (
                    acquisition_policy,
                    agent_visibility,
                    active,
                    collection_id,
                    expected_revision,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT revision FROM corpus.source_collections WHERE id = %s",
                    (collection_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise LookupError("source_collection_not_found")
                raise ValueError(f"revision_conflict:{existing['revision']}")
            row["source_code"] = self._source_code(cursor, row["source_registry_id"])
        return self._collection(row)

    def list_documents(
        self,
        *,
        source_id: UUID | None,
        collection: str | None,
        availability: str | None,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[SourceDocumentRecord, ...]:
        with self._connection_factory() as connection, connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT sd.id, sd.source_registry_id, sr.code AS source_code,
                       sd.source_identifier, sd.source_collection, sd.document_kind,
                       sd.discovery_url, sd.current_document_url,
                       sd.artifact_availability, sd.first_seen_at, sd.last_seen_at,
                       EXISTS (
                           SELECT 1 FROM corpus.source_document_artifacts sda
                           WHERE sda.source_document_id = sd.id
                       ) AS acquired
                FROM corpus.source_documents sd
                JOIN corpus.source_registries sr ON sr.id = sd.source_registry_id
                WHERE (%s::uuid IS NULL OR sd.source_registry_id = %s::uuid)
                  AND (%s::text IS NULL OR sd.source_collection = %s::text)
                  AND (%s::text IS NULL OR sd.artifact_availability = %s::text)
                  AND (%s::uuid IS NULL OR sd.id > %s::uuid)
                ORDER BY sd.id
                LIMIT %s
                """,
                (
                    source_id,
                    source_id,
                    collection,
                    collection,
                    availability,
                    availability,
                    after_id,
                    after_id,
                    limit,
                ),
            )
            return tuple(self._document(row) for row in cursor.fetchall())

    @staticmethod
    def _source_code(cursor: Any, source_id: UUID) -> str:
        cursor.execute("SELECT code FROM corpus.source_registries WHERE id = %s", (source_id,))
        row = cursor.fetchone()
        if row is None:
            raise LookupError("source_not_found")
        return str(row["code"])

    @staticmethod
    def _source(row: dict[str, Any]) -> SourceRecord:
        return SourceRecord(**row)

    @staticmethod
    def _collection(row: dict[str, Any]) -> SourceCollectionRecord:
        return SourceCollectionRecord(**row)

    @staticmethod
    def _document(row: dict[str, Any]) -> SourceDocumentRecord:
        return SourceDocumentRecord(**row)
