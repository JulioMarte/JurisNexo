"""Persist model latency and throughput metrics.

Revision ID: 0018_model_throughput_metrics
Revises: 0017_agent_run_ledger
Create Date: 2026-09-14
"""

from alembic import op

revision = "0018_model_throughput_metrics"
down_revision = "0017_agent_run_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.agent_runs
            ADD COLUMN model_time_seconds numeric(20, 6)
                GENERATED ALWAYS AS (
                    COALESCE((usage ->> 'model_time_seconds')::numeric, 0)
                ) STORED,
            ADD COLUMN output_tokens_per_second numeric(20, 6)
                GENERATED ALWAYS AS (
                    (usage ->> 'output_tokens_per_second')::numeric
                ) STORED,
            ADD COLUMN total_tokens_per_second numeric(20, 6)
                GENERATED ALWAYS AS (
                    (usage ->> 'total_tokens_per_second')::numeric
                ) STORED,
            ADD CONSTRAINT agent_runs_model_time_nonnegative_check
                CHECK (model_time_seconds >= 0),
            ADD CONSTRAINT agent_runs_output_tps_nonnegative_check
                CHECK (output_tokens_per_second IS NULL OR output_tokens_per_second >= 0),
            ADD CONSTRAINT agent_runs_total_tps_nonnegative_check
                CHECK (total_tokens_per_second IS NULL OR total_tokens_per_second >= 0)
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.structure_pipeline_runs
            ADD COLUMN model_time_seconds numeric(20, 6)
                GENERATED ALWAYS AS (
                    COALESCE((usage ->> 'model_time_seconds')::numeric, 0)
                ) STORED,
            ADD COLUMN output_tokens_per_second numeric(20, 6)
                GENERATED ALWAYS AS (
                    (usage ->> 'output_tokens_per_second')::numeric
                ) STORED,
            ADD COLUMN total_tokens_per_second numeric(20, 6)
                GENERATED ALWAYS AS (
                    (usage ->> 'total_tokens_per_second')::numeric
                ) STORED,
            ADD CONSTRAINT structure_pipeline_runs_model_time_nonnegative_check
                CHECK (model_time_seconds >= 0),
            ADD CONSTRAINT structure_pipeline_runs_output_tps_nonnegative_check
                CHECK (output_tokens_per_second IS NULL OR output_tokens_per_second >= 0),
            ADD CONSTRAINT structure_pipeline_runs_total_tps_nonnegative_check
                CHECK (total_tokens_per_second IS NULL OR total_tokens_per_second >= 0)
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.agent_runs.output_tokens_per_second IS
        'Weighted generation throughput: output tokens divided by summed model request latency.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.agent_runs.total_tokens_per_second IS
        'Gross processing throughput: total input plus output tokens divided by summed model request latency.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.structure_pipeline_runs.output_tokens_per_second IS
        'Weighted session generation throughput across all model requests in the structure pipeline.'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.structure_pipeline_runs
            DROP CONSTRAINT IF EXISTS structure_pipeline_runs_total_tps_nonnegative_check,
            DROP CONSTRAINT IF EXISTS structure_pipeline_runs_output_tps_nonnegative_check,
            DROP CONSTRAINT IF EXISTS structure_pipeline_runs_model_time_nonnegative_check,
            DROP COLUMN IF EXISTS total_tokens_per_second,
            DROP COLUMN IF EXISTS output_tokens_per_second,
            DROP COLUMN IF EXISTS model_time_seconds
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.agent_runs
            DROP CONSTRAINT IF EXISTS agent_runs_total_tps_nonnegative_check,
            DROP CONSTRAINT IF EXISTS agent_runs_output_tps_nonnegative_check,
            DROP CONSTRAINT IF EXISTS agent_runs_model_time_nonnegative_check,
            DROP COLUMN IF EXISTS total_tokens_per_second,
            DROP COLUMN IF EXISTS output_tokens_per_second,
            DROP COLUMN IF EXISTS model_time_seconds
        """
    )
