"""Add derived-artifact provenance and normalization execution ledgers.

Revision ID: 0048_doc_normalization
Revises: 0047_treatment_legal_issues
Create Date: 2026-09-19

Official source artifacts remain immutable primary evidence. Normalization,
OCR, layout analysis and other transformations produce separate immutable
derived artifacts whose lineage is explicit and reproducible.
"""

from alembic import op

revision = "0048_doc_normalization"
down_revision = "0047_treatment_legal_issues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.derived_artifacts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            sha256 text NOT NULL UNIQUE,
            artifact_kind text NOT NULL,
            mime_type text NOT NULL,
            byte_size bigint NOT NULL,
            storage_locator text NOT NULL UNIQUE,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT derived_artifacts_sha256_check
                CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT derived_artifacts_kind_nonempty
                CHECK (btrim(artifact_kind) <> ''),
            CONSTRAINT derived_artifacts_mime_nonempty
                CHECK (btrim(mime_type) <> ''),
            CONSTRAINT derived_artifacts_byte_size_check
                CHECK (byte_size >= 0),
            CONSTRAINT derived_artifacts_storage_locator_nonempty
                CHECK (btrim(storage_locator) <> ''),
            CONSTRAINT derived_artifacts_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX derived_artifacts_kind_created_idx "
        "ON corpus.derived_artifacts (artifact_kind, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE corpus.artifact_derivations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_artifact_id uuid REFERENCES corpus.source_artifacts(id),
            parent_derived_artifact_id uuid REFERENCES corpus.derived_artifacts(id),
            derived_artifact_id uuid NOT NULL REFERENCES corpus.derived_artifacts(id),
            derivation_type text NOT NULL,
            engine text NOT NULL,
            engine_version text,
            pipeline_version text NOT NULL,
            config_sha256 text NOT NULL,
            parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT artifact_derivations_exactly_one_parent_check
                CHECK (num_nonnulls(source_artifact_id, parent_derived_artifact_id) = 1),
            CONSTRAINT artifact_derivations_not_self_check
                CHECK (
                    parent_derived_artifact_id IS NULL
                    OR parent_derived_artifact_id <> derived_artifact_id
                ),
            CONSTRAINT artifact_derivations_type_nonempty
                CHECK (btrim(derivation_type) <> ''),
            CONSTRAINT artifact_derivations_engine_nonempty
                CHECK (btrim(engine) <> ''),
            CONSTRAINT artifact_derivations_pipeline_nonempty
                CHECK (btrim(pipeline_version) <> ''),
            CONSTRAINT artifact_derivations_config_sha256_check
                CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT artifact_derivations_parameters_object_check
                CHECK (jsonb_typeof(parameters) = 'object'),
            CONSTRAINT artifact_derivations_identity_key
                UNIQUE NULLS NOT DISTINCT (
                    source_artifact_id,
                    parent_derived_artifact_id,
                    derived_artifact_id,
                    derivation_type,
                    pipeline_version,
                    config_sha256
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX artifact_derivations_source_idx "
        "ON corpus.artifact_derivations (source_artifact_id, created_at DESC) "
        "WHERE source_artifact_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX artifact_derivations_parent_idx "
        "ON corpus.artifact_derivations (parent_derived_artifact_id, created_at DESC) "
        "WHERE parent_derived_artifact_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX artifact_derivations_output_idx "
        "ON corpus.artifact_derivations (derived_artifact_id)"
    )

    op.execute(
        """
        CREATE FUNCTION corpus.reject_derived_artifact_cycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            cycle_found boolean;
        BEGIN
            IF NEW.parent_derived_artifact_id IS NULL THEN
                RETURN NEW;
            END IF;

            WITH RECURSIVE descendants(id) AS (
                SELECT d.derived_artifact_id
                FROM corpus.artifact_derivations d
                WHERE d.parent_derived_artifact_id = NEW.derived_artifact_id
                UNION
                SELECT d.derived_artifact_id
                FROM corpus.artifact_derivations d
                JOIN descendants prior
                  ON d.parent_derived_artifact_id = prior.id
            )
            SELECT EXISTS (
                SELECT 1
                FROM descendants
                WHERE id = NEW.parent_derived_artifact_id
            )
            INTO cycle_found;

            IF cycle_found THEN
                RAISE EXCEPTION 'derived artifact lineage cannot contain cycles'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER artifact_derivations_no_cycle
        BEFORE INSERT OR UPDATE OF parent_derived_artifact_id, derived_artifact_id
        ON corpus.artifact_derivations
        FOR EACH ROW EXECUTE FUNCTION corpus.reject_derived_artifact_cycle()
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.normalization_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            input_manifest_locator text NOT NULL,
            input_manifest_sha256 text NOT NULL,
            pipeline_version text NOT NULL,
            config_sha256 text NOT NULL,
            status text NOT NULL DEFAULT 'queued',
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            started_at timestamptz,
            finished_at timestamptz,
            selected_count integer NOT NULL DEFAULT 0,
            normalized_count integer NOT NULL DEFAULT 0,
            review_required_count integer NOT NULL DEFAULT 0,
            failed_count integer NOT NULL DEFAULT 0,
            skipped_count integer NOT NULL DEFAULT 0,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT normalization_runs_manifest_locator_nonempty
                CHECK (btrim(input_manifest_locator) <> ''),
            CONSTRAINT normalization_runs_manifest_sha256_check
                CHECK (input_manifest_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT normalization_runs_pipeline_nonempty
                CHECK (btrim(pipeline_version) <> ''),
            CONSTRAINT normalization_runs_config_sha256_check
                CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT normalization_runs_status_check CHECK (
                status IN (
                    'queued',
                    'running',
                    'succeeded',
                    'completed_with_errors',
                    'failed',
                    'cancelled'
                )
            ),
            CONSTRAINT normalization_runs_counts_check CHECK (
                selected_count >= 0
                AND normalized_count >= 0
                AND review_required_count >= 0
                AND failed_count >= 0
                AND skipped_count >= 0
            ),
            CONSTRAINT normalization_runs_time_check CHECK (
                finished_at IS NULL
                OR started_at IS NULL
                OR finished_at >= started_at
            ),
            CONSTRAINT normalization_runs_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX normalization_runs_manifest_idx "
        "ON corpus.normalization_runs "
        "(input_manifest_sha256, requested_at DESC)"
    )
    op.execute(
        "CREATE INDEX normalization_runs_status_idx "
        "ON corpus.normalization_runs (status, requested_at)"
    )

    op.execute(
        """
        CREATE TABLE corpus.normalization_run_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id uuid NOT NULL
                REFERENCES corpus.normalization_runs(id) ON DELETE CASCADE,
            source_artifact_id uuid NOT NULL
                REFERENCES corpus.source_artifacts(id),
            status text NOT NULL DEFAULT 'pending',
            normalized_artifact_id uuid
                REFERENCES corpus.derived_artifacts(id),
            ocr_artifact_id uuid
                REFERENCES corpus.derived_artifacts(id),
            error_code text,
            error_message text,
            quality_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
            started_at timestamptz,
            finished_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT normalization_run_items_identity_key
                UNIQUE (run_id, source_artifact_id),
            CONSTRAINT normalization_run_items_status_check CHECK (
                status IN (
                    'pending',
                    'running',
                    'normalized',
                    'quality_review_required',
                    'failed',
                    'skipped'
                )
            ),
            CONSTRAINT normalization_run_items_normalized_output_check CHECK (
                status <> 'normalized' OR normalized_artifact_id IS NOT NULL
            ),
            CONSTRAINT normalization_run_items_error_pair_check CHECK (
                (error_code IS NULL) = (error_message IS NULL)
            ),
            CONSTRAINT normalization_run_items_distinct_outputs_check CHECK (
                normalized_artifact_id IS NULL
                OR ocr_artifact_id IS NULL
                OR normalized_artifact_id <> ocr_artifact_id
            ),
            CONSTRAINT normalization_run_items_quality_object_check
                CHECK (jsonb_typeof(quality_summary) = 'object'),
            CONSTRAINT normalization_run_items_time_check CHECK (
                finished_at IS NULL
                OR started_at IS NULL
                OR finished_at >= started_at
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX normalization_run_items_run_status_idx "
        "ON corpus.normalization_run_items (run_id, status)"
    )
    op.execute(
        "CREATE INDEX normalization_run_items_source_idx "
        "ON corpus.normalization_run_items (source_artifact_id, created_at DESC)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.derived_artifacts IS
        'Immutable outputs produced from preserved source artifacts or earlier derived artifacts. Large normalized payloads such as Docling JSON remain in object storage; PostgreSQL stores identity, location and provenance.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.artifact_derivations IS
        'Explicit provenance edges for OCR, document normalization, layout extraction and other transformations. A derived artifact never replaces the official source artifact.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.normalization_runs IS
        'Durable execution ledger for manifest-driven document normalization. A run references the immutable acquisition manifest that supplied its source artifacts.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.normalization_run_items IS
        'Per-source normalization outcome, including optional OCR and final normalized derived-artifact identities plus bounded quality/failure metadata.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0048 adds provenance-bearing derived artifacts and normalization history; "
        "dropping them would destroy normalization lineage"
    )
