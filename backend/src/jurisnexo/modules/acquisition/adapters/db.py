from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from psycopg.rows import dict_row

from jurisnexo.modules.acquisition.contracts import (
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    AcquisitionTarget,
    ArtifactRecord,
)
from jurisnexo.platform.db.connection import ConnectionFactory


class PostgresAcquisitionLedger:
    def __init__(self, connection_factory: ConnectionFactory, *, storage_bucket: str) -> None:
        if not storage_bucket.strip():
            raise ValueError("storage_bucket must not be empty")
        self._connection_factory = connection_factory
        self._storage_bucket = storage_bucket

    def create_run(
        self,
        *,
        source_collection_id: UUID,
        source_document_ids: tuple[UUID, ...] | None,
        limit: int,
    ) -> AcquisitionRunRecord:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT sc.id, sc.source_registry_id, sc.code, sc.acquisition_policy,
                       sc.active, sr.active AS source_active
                FROM corpus.source_collections sc
                JOIN corpus.source_registries sr ON sr.id = sc.source_registry_id
                WHERE sc.id = %s
                FOR UPDATE
                """,
                (source_collection_id,),
            )
            collection = cursor.fetchone()
            if collection is None:
                raise LookupError("source_collection_not_found")
            if not collection["active"] or not collection["source_active"]:
                raise ValueError("source_collection_inactive")
            if collection["acquisition_policy"] != "enabled":
                raise ValueError(f"acquisition_policy:{collection['acquisition_policy']}")

            explicit_ids = list(source_document_ids) if source_document_ids else None
            cursor.execute(
                """
                SELECT sd.id,
                       EXISTS (
                           SELECT 1
                           FROM corpus.source_document_artifacts sda
                           WHERE sda.source_document_id = sd.id
                       ) AS already_present
                FROM corpus.source_documents sd
                WHERE sd.source_registry_id = %s
                  AND sd.source_collection = %s
                  AND sd.artifact_availability = 'available'
                  AND sd.current_document_url IS NOT NULL
                  AND (%s::uuid[] IS NULL OR sd.id = ANY(%s::uuid[]))
                ORDER BY sd.last_seen_at DESC, sd.id
                LIMIT %s
                """,
                (
                    collection["source_registry_id"],
                    collection["code"],
                    explicit_ids,
                    explicit_ids,
                    limit,
                ),
            )
            documents = cursor.fetchall()
            if explicit_ids is not None and len(documents) != len(set(explicit_ids)):
                raise ValueError("source_documents_not_eligible")
            if not documents:
                raise ValueError("no_acquirable_documents")

            already_present = sum(1 for row in documents if row["already_present"])
            cursor.execute(
                """
                INSERT INTO corpus.acquisition_runs (
                    source_collection_id, selected_count, already_present_count
                ) VALUES (%s, %s, %s)
                RETURNING id
                """,
                (source_collection_id, len(documents), already_present),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                raise RuntimeError("acquisition run insert returned no row")
            run_id = inserted["id"]

            for document in documents:
                item_status = (
                    "already_present" if document["already_present"] else "pending"
                )
                cursor.execute(
                    """
                    INSERT INTO corpus.acquisition_run_items (
                        run_id, source_document_id, status, finished_at
                    ) VALUES (
                        %s, %s, %s,
                        CASE WHEN %s = 'already_present' THEN clock_timestamp() ELSE NULL END
                    )
                    """,
                    (run_id, document["id"], item_status, item_status),
                )

        return self.get_run(run_id)

    def get_run(self, run_id: UUID) -> AcquisitionRunRecord:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(self._run_select() + " WHERE ar.id = %s", (run_id,))
            row = cursor.fetchone()
        if row is None:
            raise LookupError("acquisition_run_not_found")
        return AcquisitionRunRecord(**row)

    def list_runs(
        self, *, after_id: UUID | None, limit: int
    ) -> tuple[AcquisitionRunRecord, ...]:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                self._run_select()
                + " WHERE (%s::uuid IS NULL OR ar.id > %s::uuid) ORDER BY ar.id LIMIT %s",
                (after_id, after_id, limit),
            )
            return tuple(AcquisitionRunRecord(**row) for row in cursor.fetchall())

    def list_run_items(
        self, *, run_id: UUID, after_id: UUID | None, limit: int
    ) -> tuple[AcquisitionRunItemRecord, ...]:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT ari.id, ari.run_id, ari.source_document_id,
                       sd.source_identifier, ari.status, ari.artifact_id,
                       ari.error_code, ari.error_message
                FROM corpus.acquisition_run_items ari
                JOIN corpus.source_documents sd ON sd.id = ari.source_document_id
                WHERE ari.run_id = %s
                  AND (%s::uuid IS NULL OR ari.id > %s::uuid)
                ORDER BY ari.id
                LIMIT %s
                """,
                (run_id, after_id, after_id, limit),
            )
            rows = cursor.fetchall()
            if not rows:
                cursor.execute(
                    "SELECT 1 FROM corpus.acquisition_runs WHERE id = %s",
                    (run_id,),
                )
                if cursor.fetchone() is None:
                    raise LookupError("acquisition_run_not_found")
            return tuple(AcquisitionRunItemRecord(**row) for row in rows)

    def claim_run(self, run_id: UUID) -> AcquisitionRunRecord:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                UPDATE corpus.acquisition_runs
                SET status = 'running', started_at = clock_timestamp()
                WHERE id = %s AND status = 'queued'
                RETURNING id
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT status FROM corpus.acquisition_runs WHERE id = %s",
                    (run_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise LookupError("acquisition_run_not_found")
                raise ValueError(f"acquisition_run_not_queued:{existing['status']}")
        return self.get_run(run_id)

    def pending_targets(self, run_id: UUID) -> tuple[AcquisitionTarget, ...]:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT ari.id AS item_id, ari.run_id, sd.id AS source_document_id,
                       sd.source_registry_id, sr.code AS source_code,
                       sd.source_identifier, sd.source_collection,
                       sd.discovery_url, sd.current_document_url AS document_url
                FROM corpus.acquisition_run_items ari
                JOIN corpus.source_documents sd ON sd.id = ari.source_document_id
                JOIN corpus.source_registries sr ON sr.id = sd.source_registry_id
                WHERE ari.run_id = %s
                  AND ari.status = 'pending'
                  AND sd.current_document_url IS NOT NULL
                ORDER BY ari.id
                """,
                (run_id,),
            )
            return tuple(AcquisitionTarget(**row) for row in cursor.fetchall())

    def mark_item_started(self, item_id: UUID) -> None:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                UPDATE corpus.acquisition_run_items
                SET started_at = COALESCE(started_at, clock_timestamp())
                WHERE id = %s AND status = 'pending'
                """,
                (item_id,),
            )

    def register_acquired_artifact(
        self,
        *,
        target: AcquisitionTarget,
        sha256: str,
        byte_size: int,
        object_key: str,
    ) -> UUID:
        storage_locator = f"s3://{self._storage_bucket}/{object_key}"
        path = PurePosixPath(unquote(urlparse(target.document_url).path))
        observed_filename = path.name or None
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO corpus.source_artifacts (
                    source_registry_id, sha256, mime_type, byte_size
                ) VALUES (%s, %s, 'application/pdf', %s)
                ON CONFLICT (sha256) DO UPDATE SET
                    source_registry_id = COALESCE(
                        corpus.source_artifacts.source_registry_id,
                        EXCLUDED.source_registry_id
                    )
                RETURNING id
                """,
                (target.source_registry_id, sha256, byte_size),
            )
            artifact_row = cursor.fetchone()
            if artifact_row is None:
                raise RuntimeError("artifact upsert returned no row")
            artifact_id: UUID = artifact_row["id"]

            self._upsert_location(
                cursor,
                artifact_id=artifact_id,
                target=target,
                locator_type="official_url",
                locator=target.document_url,
                observed_filename=observed_filename,
                discovered_via=target.discovery_url,
                preferred=False,
            )
            self._upsert_location(
                cursor,
                artifact_id=artifact_id,
                target=target,
                locator_type="storage_object",
                locator=storage_locator,
                observed_filename=PurePosixPath(object_key).name,
                discovered_via=target.document_url,
                preferred=True,
            )
            cursor.execute(
                """
                INSERT INTO corpus.source_document_artifacts (
                    source_document_id, artifact_id, relationship_type
                ) VALUES (%s, %s, 'primary')
                ON CONFLICT (source_document_id, artifact_id, relationship_type)
                DO UPDATE SET last_seen_at = clock_timestamp()
                """,
                (target.source_document_id, artifact_id),
            )
            cursor.execute(
                """
                UPDATE corpus.acquisition_run_items
                SET status = 'acquired', artifact_id = %s,
                    error_code = NULL, error_message = NULL,
                    finished_at = clock_timestamp()
                WHERE id = %s AND status = 'pending'
                """,
                (artifact_id, target.item_id),
            )
        return artifact_id

    def mark_item_failed(
        self, *, item_id: UUID, error_code: str, error_message: str
    ) -> None:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                UPDATE corpus.acquisition_run_items
                SET status = 'failed', error_code = %s, error_message = %s,
                    finished_at = clock_timestamp()
                WHERE id = %s AND status = 'pending'
                """,
                (error_code, error_message, item_id),
            )

    def finalize_run(self, run_id: UUID) -> AcquisitionRunRecord:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'acquired')::int AS acquired,
                    count(*) FILTER (WHERE status = 'already_present')::int AS already_present,
                    count(*) FILTER (WHERE status = 'failed')::int AS failed,
                    count(*) FILTER (WHERE status = 'pending')::int AS pending
                FROM corpus.acquisition_run_items
                WHERE run_id = %s
                """,
                (run_id,),
            )
            counts = cursor.fetchone()
            if counts is None:
                raise LookupError("acquisition_run_not_found")
            if counts["pending"]:
                raise ValueError("acquisition_run_has_pending_items")
            if counts["failed"] == 0:
                final_status = "succeeded"
            elif counts["acquired"] > 0 or counts["already_present"] > 0:
                final_status = "completed_with_errors"
            else:
                final_status = "failed"
            cursor.execute(
                """
                UPDATE corpus.acquisition_runs
                SET status = %s, finished_at = clock_timestamp(),
                    acquired_count = %s, already_present_count = %s, failed_count = %s
                WHERE id = %s AND status = 'running'
                """,
                (
                    final_status,
                    counts["acquired"],
                    counts["already_present"],
                    counts["failed"],
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def list_artifacts(
        self, *, after_id: UUID | None, limit: int
    ) -> tuple[ArtifactRecord, ...]:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT sa.id, sa.source_registry_id, sr.code AS source_code,
                       sa.sha256, sa.mime_type, sa.byte_size, sa.parser_status,
                       storage.locator AS storage_locator, sa.acquired_at
                FROM corpus.source_artifacts sa
                LEFT JOIN corpus.source_registries sr ON sr.id = sa.source_registry_id
                LEFT JOIN LATERAL (
                    SELECT locator
                    FROM corpus.source_artifact_locations sal
                    WHERE sal.artifact_id = sa.id
                      AND sal.locator_type = 'storage_object'
                    ORDER BY sal.is_preferred DESC, sal.last_seen_at DESC
                    LIMIT 1
                ) storage ON true
                WHERE (%s::uuid IS NULL OR sa.id > %s::uuid)
                ORDER BY sa.id
                LIMIT %s
                """,
                (after_id, after_id, limit),
            )
            return tuple(ArtifactRecord(**row) for row in cursor.fetchall())

    @staticmethod
    def _run_select() -> str:
        return """
            SELECT ar.id, ar.source_collection_id, sr.code AS source_code,
                   sc.code AS collection_code, ar.status, ar.requested_at,
                   ar.started_at, ar.finished_at, ar.selected_count,
                   ar.acquired_count, ar.already_present_count, ar.failed_count
            FROM corpus.acquisition_runs ar
            JOIN corpus.source_collections sc ON sc.id = ar.source_collection_id
            JOIN corpus.source_registries sr ON sr.id = sc.source_registry_id
        """

    @staticmethod
    def _upsert_location(
        cursor: Any,
        *,
        artifact_id: UUID,
        target: AcquisitionTarget,
        locator_type: str,
        locator: str,
        observed_filename: str | None,
        discovered_via: str,
        preferred: bool,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO corpus.source_artifact_locations (
                artifact_id, source_registry_id, source_identifier,
                source_collection, locator_type, locator, observed_filename,
                discovered_via, is_preferred, first_seen_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                      clock_timestamp(), clock_timestamp())
            ON CONFLICT (artifact_id, locator_type, locator) DO UPDATE SET
                source_registry_id = EXCLUDED.source_registry_id,
                source_identifier = EXCLUDED.source_identifier,
                source_collection = EXCLUDED.source_collection,
                observed_filename = COALESCE(
                    EXCLUDED.observed_filename,
                    corpus.source_artifact_locations.observed_filename
                ),
                discovered_via = EXCLUDED.discovered_via,
                is_preferred = EXCLUDED.is_preferred,
                last_seen_at = clock_timestamp()
            """,
            (
                artifact_id,
                target.source_registry_id,
                target.source_identifier,
                target.source_collection,
                locator_type,
                locator,
                observed_filename,
                discovered_via,
                preferred,
            ),
        )
