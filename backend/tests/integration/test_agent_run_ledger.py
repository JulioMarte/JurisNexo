from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from jurisnexo.corpus.agent_run_ledger import PostgresAgentRunLedger
from jurisnexo.model_providers.usage_accounting import ModelTurnUsage, PricingSnapshot

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
        insert into corpus.ingestion_jobs (artifact_id, parser_version_id, idempotency_key)
        values (%s, %s, %s)
        returning id
        """,
        (artifact_id, parser_version_id, f"agent-run-job:{suffix}"),
    )
    return artifact_id, _scalar(cursor)


def _usage_turn() -> ModelTurnUsage:
    pricing = PricingSnapshot(
        provider="deepseek",
        model="deepseek-v4-flash",
        model_version="DeepSeek-V4-Flash-0731",
        effective_from_utc=datetime(2026, 8, 16, 16, tzinfo=UTC),
        pricing_band="off_peak",
        execution_mode="realtime",
        input_cache_hit_per_million_usd=Decimal("0.007"),
        input_cache_miss_per_million_usd=Decimal("0.22"),
        output_per_million_usd=Decimal("0.66"),
        source="https://api-docs.deepseek.com/quick_start/pricing/",
    )
    now = datetime.now(UTC)
    return ModelTurnUsage(
        session_turn=1,
        run_turn=1,
        role="structure_agent",
        round_number=0,
        request_started_at=now,
        response_completed_at=now,
        provider="deepseek",
        model="deepseek-v4-flash",
        input_tokens=1_500,
        output_tokens=500,
        total_tokens=2_000,
        input_cache_hit_tokens=1_000,
        input_cache_miss_tokens=500,
        reasoning_tokens=100,
        estimated_cost_usd=Decimal("0.000447"),
        session_total_tokens_after_turn=2_000,
        session_estimated_cost_usd_after_turn=Decimal("0.000447"),
        pricing=pricing,
        response_id="response-1",
        request_id="request-1",
    )


def test_agent_run_event_sequence_and_pipeline_state_are_durable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_id, ingestion_job_id = _create_job(cursor, suffix="a17")
    ledger = PostgresAgentRunLedger(connection)
    pipeline_id = ledger.create_structure_pipeline_run(
        ingestion_job_id=ingestion_job_id,
        artifact_id=artifact_id,
        idempotency_key="structure-pipeline:a17",
    )
    run_id = ledger.create_agent_run(
        ingestion_job_id=ingestion_job_id,
        artifact_id=artifact_id,
        role="structure_agent",
        round_number=0,
        provider="deepseek",
        model="deepseek-v4-flash",
        prompt_sha256="a" * 64,
        tool_budget={"max_turns": 128},
    )
    turn = _usage_turn()
    ledger.append_model_turn(run_id=run_id, event=turn)
    usage = {
        "request_count": 1,
        "input_tokens": 1_500,
        "output_tokens": 500,
        "total_tokens": 2_000,
        "input_cache_hit_tokens": 1_000,
        "input_cache_miss_tokens": 500,
        "reasoning_tokens": 100,
        "estimated_cost_usd": "0.000447",
    }
    ledger.complete_agent_run(run_id=run_id, usage=usage)
    ledger.record_structure_pipeline_usage(pipeline_run_id=pipeline_id, usage=usage)
    ledger.transition_structure_pipeline(
        pipeline_run_id=pipeline_id,
        target_state="structure_candidate",
        structure_run_id=run_id,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select request_count, input_tokens, output_tokens, total_tokens,
                   input_cache_hit_tokens, input_cache_miss_tokens,
                   reasoning_tokens, estimated_cost_usd
            from corpus.agent_runs where id = %s
            """,
            (run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[:7] == (1, 1_500, 500, 2_000, 1_000, 500, 100)
        assert row[7] == Decimal("0.0004470000")
        cursor.execute(
            "select event_type, payload->>'session_turn' from corpus.agent_run_events where run_id = %s",
            (run_id,),
        )
        assert cursor.fetchone() == ("model_turn", "1")


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
                insert into corpus.agent_runs (ingestion_job_id, artifact_id, role, state)
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
            insert into corpus.agent_runs (ingestion_job_id, artifact_id, role, state)
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
                    ingestion_job_id, artifact_id, idempotency_key, state, structure_run_id
                )
                values (%s, %s, %s, 'structure_candidate', %s)
                """,
                (job_one, artifact_one, "structure-pipeline:d17", foreign_run_id),
            )


def test_agent_run_role_state_and_usage_are_constrained(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        artifact_id, ingestion_job_id = _create_job(cursor, suffix="f17")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.agent_runs (ingestion_job_id, artifact_id, role, state)
                values (%s, %s, 'unbounded_super_agent', 'running')
                """,
                (ingestion_job_id, artifact_id),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                insert into corpus.agent_runs (
                    ingestion_job_id, artifact_id, role, state, total_tokens
                )
                values (%s, %s, 'structure_agent', 'running', -1)
                """,
                (ingestion_job_id, artifact_id),
            )
