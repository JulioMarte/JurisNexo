"""Add parser versions, ingestion jobs, and metadata observations.

Revision ID: 0004_ingest_observations
Revises: 0003_case_page_provenance
Create Date: 2026-09-11
"""

from alembic import op

revision = "0004_ingest_observations"
down_revision = "0003_case_page_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.parser_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            parser_name text NOT NULL,
            parser_version text NOT NULL,
            code_revision text,
            configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
            configuration_sha256 text,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (parser_name, parser_version),
            CONSTRAINT parser_versions_configuration_sha256_check
                CHECK (configuration_sha256 IS NULL OR configuration_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.ingestion_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id uuid NOT NULL REFERENCES corpus.source_artifacts(id),
            parser_version_id uuid NOT NULL REFERENCES corpus.parser_versions(id),
            idempotency_key text NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'pending',
            attempt integer NOT NULL DEFAULT 1,
            started_at timestamptz,
            finished_at timestamptz,
            error_code text,
            error_detail text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ingestion_jobs_state_check
                CHECK (state IN (
                    'pending',
                    'extracting',
                    'segmenting',
                    'observing_metadata',
                    'reconciling',
                    'quality_check',
                    'ready',
                    'partial',
                    'failed',
                    'cancelled',
                    'blocked'
                )),
            CONSTRAINT ingestion_jobs_attempt_check CHECK (attempt > 0),
            CONSTRAINT ingestion_jobs_finished_after_started_check
                CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.case_metadata_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ingestion_job_id uuid NOT NULL REFERENCES corpus.ingestion_jobs(id) ON DELETE CASCADE,
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            observation_key text NOT NULL,
            field_name text NOT NULL,
            value_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_text text,
            normalized_date date,
            normalized_json jsonb,
            observation_method text NOT NULL,
            method_name text NOT NULL,
            confidence real,
            evidence_case_page_id uuid,
            evidence_excerpt text,
            evidence_char_start integer,
            evidence_char_end integer,
            status text NOT NULL DEFAULT 'observed',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (ingestion_job_id, observation_key),
            CONSTRAINT case_metadata_observations_key_check
                CHECK (observation_key ~ '^[0-9a-f]{64}$'),
            CONSTRAINT case_metadata_observations_value_type_check
                CHECK (value_type IN ('text', 'date', 'identifier', 'json')),
            CONSTRAINT case_metadata_observations_method_check
                CHECK (observation_method IN (
                    'deterministic_parser',
                    'official_metadata_import',
                    'llm_assist',
                    'manual_review'
                )),
            CONSTRAINT case_metadata_observations_status_check
                CHECK (status IN ('observed', 'accepted', 'rejected', 'conflicting', 'superseded')),
            CONSTRAINT case_metadata_observations_confidence_check
                CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CONSTRAINT case_metadata_observations_normalized_shape_check
                CHECK (
                    (value_type = 'date' AND normalized_text IS NULL AND normalized_json IS NULL)
                    OR (
                        value_type IN ('text', 'identifier')
                        AND normalized_date IS NULL
                        AND normalized_json IS NULL
                    )
                    OR (
                        value_type = 'json'
                        AND normalized_text IS NULL
                        AND normalized_date IS NULL
                    )
                ),
            CONSTRAINT case_metadata_observations_offsets_check
                CHECK (
                    (evidence_char_start IS NULL AND evidence_char_end IS NULL)
                    OR (
                        evidence_char_start IS NOT NULL
                        AND evidence_char_end IS NOT NULL
                        AND evidence_char_start >= 0
                        AND evidence_char_end > evidence_char_start
                    )
                ),
            CONSTRAINT case_metadata_observations_evidence_same_case_fkey
                FOREIGN KEY (case_id, evidence_case_page_id)
                REFERENCES corpus.case_pages (case_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )

    op.execute(
        "CREATE INDEX ingestion_jobs_artifact_idx "
        "ON corpus.ingestion_jobs (artifact_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ingestion_jobs_parser_version_idx "
        "ON corpus.ingestion_jobs (parser_version_id)"
    )
    op.execute(
        "CREATE INDEX case_metadata_observations_case_field_idx "
        "ON corpus.case_metadata_observations (case_id, field_name, status)"
    )
    op.execute(
        "CREATE INDEX case_metadata_observations_date_idx "
        "ON corpus.case_metadata_observations (case_id, normalized_date) "
        "WHERE normalized_date IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX case_metadata_observations_evidence_page_idx "
        "ON corpus.case_metadata_observations (evidence_case_page_id) "
        "WHERE evidence_case_page_id IS NOT NULL"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.case_metadata_observations IS
        'Auditable extracted observations. Rows are evidence-bearing candidates, not canonical legal metadata until reconciliation or verification promotes them.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.case_metadata_observations.confidence IS
        'Optional calibrated score. Deterministic parsers should leave this NULL unless the score has an explicit measured calibration.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.case_metadata_observations.observation_key IS
        'Stable parser-generated SHA-256 key used to make observation writes idempotent inside one ingestion job.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.case_metadata_observations")
    op.execute("DROP TABLE IF EXISTS corpus.ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS corpus.parser_versions")
