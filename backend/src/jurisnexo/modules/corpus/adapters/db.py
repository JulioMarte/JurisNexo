from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from jurisnexo.modules.corpus.contracts import AnalysisObservationRecord
from jurisnexo.platform.db.connection import ConnectionFactory

PUBLIC_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")


class PostgresAnalysisObservationStore:
    """Public-corpus observation ledger.

    Scope is deliberately server-owned. Agents cannot choose an organization scope
    through this adapter; private-scope submission must later be composed from
    authenticated server context.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def create_observation(
        self,
        *,
        observation_key: str,
        subject_type: str,
        case_id: UUID | None,
        proceeding_id: UUID | None,
        legal_document_id: UUID | None,
        observation_type: str,
        payload: dict[str, Any],
        evidence: list[Any],
        producer_type: str,
        producer_name: str,
        model_name: str | None,
        model_version: str | None,
        analysis_run_id: str | None,
        schema_hint: str | None,
        confidence: float | None,
    ) -> AnalysisObservationRecord:
        try:
            with (
                self._connection_factory() as connection,
                connection.transaction(),
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                cursor.execute(
                    """
                    INSERT INTO corpus.analysis_observations (
                        scope_id, observation_key, subject_type, case_id,
                        proceeding_id, legal_document_id, observation_type,
                        payload, evidence, producer_type, producer_name,
                        model_name, model_version, analysis_run_id, schema_hint,
                        confidence
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        PUBLIC_SCOPE_ID,
                        observation_key,
                        subject_type,
                        case_id,
                        proceeding_id,
                        legal_document_id,
                        observation_type,
                        Jsonb(payload),
                        Jsonb(evidence),
                        producer_type,
                        producer_name,
                        model_name,
                        model_version,
                        analysis_run_id,
                        schema_hint,
                        confidence,
                    ),
                )
                row = cursor.fetchone()
        except UniqueViolation as exc:
            raise ValueError("analysis_observation_key_exists") from exc
        except ForeignKeyViolation as exc:
            raise LookupError("analysis_observation_subject_not_found") from exc
        if row is None:
            raise RuntimeError("analysis observation insert returned no row")
        return self._record(row)

    def list_observations(
        self,
        *,
        status: str | None,
        subject_type: str | None,
        observation_type: str | None,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[AnalysisObservationRecord, ...]:
        with (
            self._connection_factory() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                SELECT *
                FROM corpus.analysis_observations
                WHERE scope_id = %s
                  AND (%s::text IS NULL OR status = %s::text)
                  AND (%s::text IS NULL OR subject_type = %s::text)
                  AND (%s::text IS NULL OR observation_type = %s::text)
                  AND (%s::uuid IS NULL OR id > %s::uuid)
                ORDER BY id
                LIMIT %s
                """,
                (
                    PUBLIC_SCOPE_ID,
                    status,
                    status,
                    subject_type,
                    subject_type,
                    observation_type,
                    observation_type,
                    after_id,
                    after_id,
                    limit,
                ),
            )
            return tuple(self._record(row) for row in cursor.fetchall())

    def review_observation(
        self,
        *,
        observation_id: UUID,
        status: str,
        review_notes: str | None,
        promoted_to_schema: str | None,
    ) -> AnalysisObservationRecord:
        with (
            self._connection_factory() as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                UPDATE corpus.analysis_observations
                SET status = %s,
                    review_notes = %s,
                    promoted_to_schema = %s,
                    reviewed_at = clock_timestamp()
                WHERE id = %s AND scope_id = %s
                RETURNING *
                """,
                (
                    status,
                    review_notes,
                    promoted_to_schema,
                    observation_id,
                    PUBLIC_SCOPE_ID,
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise LookupError("analysis_observation_not_found")
        return self._record(row)

    @staticmethod
    def _record(row: dict[str, Any]) -> AnalysisObservationRecord:
        return AnalysisObservationRecord(
            id=row["id"],
            observation_key=str(row["observation_key"]),
            subject_type=str(row["subject_type"]),
            case_id=row["case_id"],
            proceeding_id=row["proceeding_id"],
            legal_document_id=row["legal_document_id"],
            observation_type=str(row["observation_type"]),
            payload=dict(row["payload"]),
            evidence=list(row["evidence"]),
            producer_type=str(row["producer_type"]),
            producer_name=str(row["producer_name"]),
            model_name=row["model_name"],
            model_version=row["model_version"],
            analysis_run_id=row["analysis_run_id"],
            schema_hint=row["schema_hint"],
            confidence=row["confidence"],
            status=str(row["status"]),
            review_notes=row["review_notes"],
            promoted_to_schema=row["promoted_to_schema"],
            created_at=row["created_at"],
            reviewed_at=row["reviewed_at"],
        )
