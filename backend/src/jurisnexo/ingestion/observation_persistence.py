from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

import psycopg

from jurisnexo.ingestion.scj_metadata import MetadataObservation, ObservationValueType


@dataclass(frozen=True, slots=True)
class ObservationPersistenceContext:
    ingestion_job_id: UUID
    artifact_id: UUID
    case_id: UUID
    case_page_ids_by_page_number: Mapping[int, UUID]


def _normalized_values(
    observation: MetadataObservation,
) -> tuple[str | None, object | None, None]:
    if observation.value_type is ObservationValueType.DATE:
        return None, observation.normalized_date, None
    return observation.normalized_text, None, None


def persist_metadata_observations(
    connection: psycopg.Connection[object],
    *,
    context: ObservationPersistenceContext,
    observations: Sequence[MetadataObservation],
) -> int:
    """Persist deterministic metadata observations idempotently.

    Cross-case, cross-artifact, and job/artifact provenance are deliberately
    enforced by PostgreSQL foreign keys. This adapter only resolves parser page
    numbers to case-owned page IDs and translates typed normalized values.
    """

    inserted = 0
    with connection.cursor() as cursor:
        for observation in observations:
            try:
                evidence_case_page_id = context.case_page_ids_by_page_number[
                    observation.page_number
                ]
            except KeyError as exc:
                raise KeyError(
                    "No case_page_id mapping for parser page number "
                    f"{observation.page_number}"
                ) from exc

            normalized_text, normalized_date, normalized_json = _normalized_values(
                observation
            )
            cursor.execute(
                """
                INSERT INTO corpus.case_metadata_observations (
                    ingestion_job_id,
                    artifact_id,
                    case_id,
                    observation_key,
                    field_name,
                    value_type,
                    raw_value,
                    normalized_text,
                    normalized_date,
                    normalized_json,
                    observation_method,
                    method_name,
                    evidence_case_page_id,
                    evidence_excerpt,
                    evidence_char_start,
                    evidence_char_end
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, 'deterministic_parser', %s, %s, %s, %s, %s
                )
                ON CONFLICT (ingestion_job_id, observation_key) DO NOTHING
                """,
                (
                    context.ingestion_job_id,
                    context.artifact_id,
                    context.case_id,
                    observation.observation_key,
                    observation.field_name,
                    observation.value_type.value,
                    observation.raw_value,
                    normalized_text,
                    normalized_date,
                    normalized_json,
                    observation.method_name,
                    evidence_case_page_id,
                    observation.raw_value,
                    observation.char_start,
                    observation.char_end,
                ),
            )
            inserted += cursor.rowcount

    return inserted
