from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _scalar(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _create_job(cursor: psycopg.Cursor[Any], *, suffix: str) -> tuple[Any, Any]:
    cursor.execute(
        """
        insert into corpus.source_registries (code, name, institution, authority_class)
        values (%s, %s, 'Poder Judicial', 'official_primary')
        returning id
        """,
        (f"AGENT-RUN-{suffix}", f"Agent run registry {suffix}"),
    )
    registry_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.source_artifacts (
            source_registry_id, sha256, mime_type, byte_size, page_count
        )
        values (%s, %s, 'application/pdf', 100, 1)
        returning id
        """,
        (registry_id, suffix.lower().zfill(64)[-64:]),
    )
    artifact_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.parser_versions (parser_name, parser_version, code_revision)
        values ('agent-run-ledger-test', %s, 'test-revision')
        returning id
        """,
        (suffix,),
    )
    parser_version_id = _scalar(cursor)

    cursor.execute(
        """
        insert into corpus.ingestion_jobs (
            artifact_id, parser_version_id, idempotency_key
        )
        values (%s, %s, %s)
        returning id
        """,
        (artifact_id, parser_version_id, f"agent-run-job:{suffix}"),
    )
    return artifact_id, _scalar(cursor)


def test_agent_run_event_sequence_and_pipeline_state_are_durable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_id, ingestion_job_id = _create_job(cursor, suffix="a17")
        cursor.execute(
            """
            insert into corpus.agent_runs (
                ingestion_job_id,
                artifact_id,
                role,
                state,
                provider,
                model,
                prompt_sha256,
                started_at
            )
            values (%s, %s, 'structure_agent', 'running', 'gemini', 'fake', %s, now())
            returning id
            """,
            (ingestion_job_id, artifact_id, "a" * 64),
        )
        run_id = _scalar(cursor)

        cursor.execute(
            """
            insert into corpus.agent_run_events (
                run_id,
                sequence,
                event_type,
                status,
                tool_name,
                arguments,
                result_char_count,
                result_sha256
            )
            values (%s, 1, 'tool_result', 'success', 'get_page', '{"page_number": 1}', 42, %s)
            """,
            (run_id, "b" * 64),
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                insert into corpus.agent_run_events (
                    run_id, sequence, event_type, status
                )
                values (%s, 1, 'duplicate', 'info')
                """,
                (run_id,),
            )

        cursor.execute(
            """
            insert into corpus.structure_pipeline_runs (
                ingestion_job_id,
                artifact_id,
                idempotency_key,
                state,
                structure_run_id
            )
            values (%s, %s, %s, 'structure_candidate', %s)
            returning id
            """,
            (ingestion_job_id, artifact_id, "structure-pipeline:a17", run_id),
        )
        pipeline_id = _scalar(cursor)
        assert pipeline_id is not None


def test_agent_run_cannot_claim_an_artifact_from_another_ingestion_job(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_one, job_one = _create_job(cursor, suffix="b17")
        artifact_two, _job_two = _create_job(cursor, suffix="c17")
        assert artifact_one != artifact_two

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                insert into corpus.agent_runs (
                    ingestion_job_id, artifact_id, role, state
                )
                values (%s, %s, 'structure_agent', 'pending')
                """,
                (job_one, artifact_two),
            )


def test_pipeline_cannot_reference_agent_run_from_another_artifact(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_one, job_one = _create_job(cursor, suffix="d17")
        artifact_two, job_two = _create_job(cursor, suffix="e17")

        cursor.execute(
            """
            insert into corpus.agent_runs (
                ingestion_job_id, artifact_id, role, state
            )
            values (%s, %s, 'structure_agent', 'completed')
            returning id
            """,
            (job_two, artifact_two),
        )
        foreign_run_id = _scalar(cursor)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                insert into corpus.structure_pipeline_runs (
                    ingestion_job_id,
                    artifact_id,
                    idempotency_key,
                    state,
                    structure_run_id
                )
                values (%s, %s, %s, 'structure_candidate', %s)
                """,
                (job_one, artifact_one, "structure-pipeline:d17", foreign_run_id),
            )


def test_agent_run_role_and_state_are_constrained(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_id, ingestion_job_id = _create_job(cursor, suffix="f17")

        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.agent_runs (
                    ingestion_job_id, artifact_id, role, state
                )
                values (%s, %s, 'unbounded_super_agent', 'running')
                """,
                (ingestion_job_id, artifact_id),
            )