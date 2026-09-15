"""Add ingestion control-plane collections and acquisition runs.

Revision ID: 0017_ingestion_control
Revises: 0016_source_obs_idempotency
Create Date: 2026-09-15

The corpus already preserves source records and immutable artifacts. This revision
adds the operator-facing policy and execution ledger needed to decide which
collections may be acquired and to make acquisition runs durable/reproducible.
"""

from alembic import op

revision = "0017_ingestion_control"
down_revision = "0016_source_obs_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.source_collections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_registry_id uuid NOT NULL REFERENCES corpus.source_registries(id) ON DELETE CASCADE,
            code text NOT NULL,
            document_kind text NOT NULL,
            acquisition_policy text NOT NULL DEFAULT 'catalog_only',
            agent_visibility text NOT NULL DEFAULT 'hidden',
            active boolean NOT NULL DEFAULT true,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_registry_id, code),
            CONSTRAINT source_collections_code_check CHECK (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            CONSTRAINT source_collections_kind_nonempty CHECK (btrim(document_kind) <> ''),
            CONSTRAINT source_collections_acquisition_policy_check CHECK (
                acquisition_policy IN ('enabled', 'catalog_only', 'paused', 'blocked')
            ),
            CONSTRAINT source_collections_agent_visibility_check CHECK (
                agent_visibility IN ('hidden', 'discoverable', 'searchable')
            ),
            CONSTRAINT source_collections_revision_check CHECK (revision > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX source_collections_source_idx ON corpus.source_collections (source_registry_id, active)"
    )
    op.execute(
        """
        INSERT INTO corpus.source_collections (
            source_registry_id, code, document_kind, acquisition_policy, agent_visibility
        )
        SELECT source_registry_id, source_collection, min(document_kind), 'catalog_only', 'hidden'
        FROM corpus.source_documents
        GROUP BY source_registry_id, source_collection
        ON CONFLICT (source_registry_id, code) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.acquisition_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_collection_id uuid NOT NULL REFERENCES corpus.source_collections(id),
            status text NOT NULL DEFAULT 'queued',
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            started_at timestamptz,
            finished_at timestamptz,
            selected_count integer NOT NULL DEFAULT 0,
            acquired_count integer NOT NULL DEFAULT 0,
            already_present_count integer NOT NULL DEFAULT 0,
            failed_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT acquisition_runs_status_check CHECK (
                status IN ('queued', 'running', 'succeeded', 'completed_with_errors', 'failed', 'cancelled')
            ),
            CONSTRAINT acquisition_runs_counts_check CHECK (
                selected_count >= 0 AND acquired_count >= 0
                AND already_present_count >= 0 AND failed_count >= 0
            ),
            CONSTRAINT acquisition_runs_time_check CHECK (
                finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX acquisition_runs_collection_time_idx "
        "ON corpus.acquisition_runs (source_collection_id, requested_at DESC)"
    )
    op.execute(
        "CREATE INDEX acquisition_runs_status_idx ON corpus.acquisition_runs (status, requested_at)"
    )

    op.execute(
        """
        CREATE TABLE corpus.acquisition_run_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id uuid NOT NULL REFERENCES corpus.acquisition_runs(id) ON DELETE CASCADE,
            source_document_id uuid NOT NULL REFERENCES corpus.source_documents(id),
            status text NOT NULL DEFAULT 'pending',
            artifact_id uuid REFERENCES corpus.source_artifacts(id),
            error_code text,
            error_message text,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (run_id, source_document_id),
            CONSTRAINT acquisition_run_items_status_check CHECK (
                status IN ('pending', 'acquired', 'already_present', 'failed', 'skipped')
            ),
            CONSTRAINT acquisition_run_items_error_pair_check CHECK (
                (error_code IS NULL) = (error_message IS NULL)
            ),
            CONSTRAINT acquisition_run_items_time_check CHECK (
                finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX acquisition_run_items_run_status_idx "
        "ON corpus.acquisition_run_items (run_id, status)"
    )
    op.execute(
        "CREATE INDEX acquisition_run_items_document_idx "
        "ON corpus.acquisition_run_items (source_document_id, created_at DESC)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.source_collections IS
        'Operator-controlled acquisition and agent-visibility policy for a source-native collection. Discovery alone never enables acquisition.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.acquisition_runs IS
        'Durable acquisition execution ledger. API requests create runs; workers or explicit execute commands perform external I/O after the run transaction commits.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.acquisition_run_items IS
        'Per-source-document acquisition outcomes. S3 bytes and canonical legal identity remain separate concerns.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.acquisition_run_items")
    op.execute("DROP TABLE IF EXISTS corpus.acquisition_runs")
    op.execute("DROP TABLE IF EXISTS corpus.source_collections")
