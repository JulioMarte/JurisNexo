"""Persist durable agent runs, events, and structure-pipeline state.

Revision ID: 0017_agent_run_ledger
Revises: 0016_source_observation_idempotency
Create Date: 2026-09-14
"""

from alembic import op

revision = "0017_agent_run_ledger"
down_revision = "0016_source_observation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.agent_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ingestion_job_id uuid NOT NULL,
            artifact_id uuid NOT NULL,
            parent_run_id uuid REFERENCES corpus.agent_runs(id),
            role text NOT NULL,
            round_number smallint NOT NULL DEFAULT 0,
            state text NOT NULL DEFAULT 'pending',
            provider text,
            model text,
            prompt_sha256 text,
            tool_budget jsonb NOT NULL DEFAULT '{}'::jsonb,
            usage jsonb NOT NULL DEFAULT '{}'::jsonb,
            trace_object_ref text,
            result_object_ref text,
            started_at timestamptz,
            finished_at timestamptz,
            error_type text,
            error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT agent_runs_job_artifact_fkey
                FOREIGN KEY (ingestion_job_id, artifact_id)
                REFERENCES corpus.ingestion_jobs (id, artifact_id)
                ON DELETE CASCADE,
            CONSTRAINT agent_runs_role_check
                CHECK (role IN (
                    'structure_agent',
                    'structure_auditor',
                    'structure_reinvestigation',
                    'extraction_agent',
                    'extraction_auditor'
                )),
            CONSTRAINT agent_runs_state_check
                CHECK (state IN (
                    'pending',
                    'running',
                    'completed',
                    'failed',
                    'budget_exhausted',
                    'cancelled',
                    'blocked'
                )),
            CONSTRAINT agent_runs_round_check CHECK (round_number >= 0),
            CONSTRAINT agent_runs_prompt_sha256_check
                CHECK (prompt_sha256 IS NULL OR prompt_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT agent_runs_finished_after_started_check
                CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
            CONSTRAINT agent_runs_ingestion_artifact_id_key
                UNIQUE (ingestion_job_id, artifact_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_runs_job_role_idx "
        "ON corpus.agent_runs (ingestion_job_id, role, round_number, created_at)"
    )
    op.execute(
        "CREATE INDEX agent_runs_artifact_state_idx "
        "ON corpus.agent_runs (artifact_id, state, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE corpus.agent_run_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id uuid NOT NULL REFERENCES corpus.agent_runs(id) ON DELETE CASCADE,
            sequence integer NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            event_type text NOT NULL,
            status text NOT NULL DEFAULT 'info',
            tool_name text,
            arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
            result_char_count integer NOT NULL DEFAULT 0,
            result_sha256 text,
            result_excerpt text,
            result_object_ref text,
            error_type text,
            error_message text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (run_id, sequence),
            CONSTRAINT agent_run_events_sequence_check CHECK (sequence > 0),
            CONSTRAINT agent_run_events_status_check
                CHECK (status IN ('info', 'success', 'error')),
            CONSTRAINT agent_run_events_result_char_count_check
                CHECK (result_char_count >= 0),
            CONSTRAINT agent_run_events_result_sha256_check
                CHECK (result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX agent_run_events_run_occurred_idx "
        "ON corpus.agent_run_events (run_id, sequence, occurred_at)"
    )

    op.execute(
        """
        CREATE TABLE corpus.structure_pipeline_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ingestion_job_id uuid NOT NULL,
            artifact_id uuid NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'structure_investigating',
            round_number smallint NOT NULL DEFAULT 0,
            structure_run_id uuid,
            audit_run_id uuid,
            page_map_object_ref text,
            structure_result_object_ref text,
            audit_result_object_ref text,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            last_error_type text,
            last_error_message text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT structure_pipeline_runs_job_artifact_fkey
                FOREIGN KEY (ingestion_job_id, artifact_id)
                REFERENCES corpus.ingestion_jobs (id, artifact_id)
                ON DELETE CASCADE,
            CONSTRAINT structure_pipeline_runs_structure_run_fkey
                FOREIGN KEY (ingestion_job_id, artifact_id, structure_run_id)
                REFERENCES corpus.agent_runs (ingestion_job_id, artifact_id, id),
            CONSTRAINT structure_pipeline_runs_audit_run_fkey
                FOREIGN KEY (ingestion_job_id, artifact_id, audit_run_id)
                REFERENCES corpus.agent_runs (ingestion_job_id, artifact_id, id),
            CONSTRAINT structure_pipeline_runs_state_check
                CHECK (state IN (
                    'structure_investigating',
                    'structure_candidate',
                    'structure_auditing',
                    'structure_reinvestigating',
                    'structure_verified',
                    'structure_rejected',
                    'source_quality_blocked',
                    'failed',
                    'cancelled'
                )),
            CONSTRAINT structure_pipeline_runs_round_check CHECK (round_number >= 0),
            CONSTRAINT structure_pipeline_runs_finished_after_started_check
                CHECK (finished_at IS NULL OR finished_at >= started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX structure_pipeline_runs_job_state_idx "
        "ON corpus.structure_pipeline_runs (ingestion_job_id, state, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX structure_pipeline_runs_artifact_state_idx "
        "ON corpus.structure_pipeline_runs (artifact_id, state, updated_at DESC)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.agent_runs IS
        'Durable execution ledger for LLM agent stages. Heavy traces/results may live in object storage and are referenced from this table.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.agent_run_events IS
        'Append-only observable event journal for an agent run. It stores evidence/tool metadata, not private chain-of-thought.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.structure_pipeline_runs IS
        'Canonical resumable state for structure discovery, adversarial audit, and bounded reinvestigation before extraction is allowed.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.structure_pipeline_runs")
    op.execute("DROP TABLE IF EXISTS corpus.agent_run_events")
    op.execute("DROP TABLE IF EXISTS corpus.agent_runs")