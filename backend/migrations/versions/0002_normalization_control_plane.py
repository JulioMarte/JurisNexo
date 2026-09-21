"""Add normalization control-plane persistence.

Revision ID: 0002_normalization_control
Revises: baseline_20260919
Create Date: 2026-09-20
"""

from alembic import op

revision = "0002_normalization_control"
down_revision = "baseline_20260919"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE corpus.derived_artifacts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
            REFERENCES corpus.scopes(id),
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        artifact_kind text NOT NULL CHECK (btrim(artifact_kind) <> ''),
        mime_type text NOT NULL CHECK (btrim(mime_type) <> ''),
        byte_size bigint NOT NULL CHECK (byte_size >= 0),
        storage_locator text NOT NULL UNIQUE CHECK (btrim(storage_locator) <> ''),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (scope_id, id),
        UNIQUE (scope_id, sha256, artifact_kind)
    );

    CREATE TABLE corpus.artifact_derivations (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
            REFERENCES corpus.scopes(id),
        source_artifact_id uuid,
        parent_derived_artifact_id uuid,
        derived_artifact_id uuid NOT NULL,
        derivation_type text NOT NULL CHECK (btrim(derivation_type) <> ''),
        engine text NOT NULL CHECK (btrim(engine) <> ''),
        engine_version text,
        pipeline_version text NOT NULL CHECK (btrim(pipeline_version) <> ''),
        config_sha256 text NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
        parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (num_nonnulls(source_artifact_id, parent_derived_artifact_id) = 1),
        CHECK (
            parent_derived_artifact_id IS NULL
            OR parent_derived_artifact_id <> derived_artifact_id
        ),
        FOREIGN KEY (scope_id, source_artifact_id)
            REFERENCES corpus.source_artifacts(scope_id, id),
        FOREIGN KEY (scope_id, parent_derived_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id),
        FOREIGN KEY (scope_id, derived_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id),
        UNIQUE NULLS NOT DISTINCT (
            scope_id, source_artifact_id, parent_derived_artifact_id, derived_artifact_id,
            derivation_type, pipeline_version, config_sha256
        )
    );

    CREATE TABLE corpus.artifact_derivation_paths (
        scope_id uuid NOT NULL REFERENCES corpus.scopes(id),
        ancestor_artifact_id uuid NOT NULL,
        descendant_artifact_id uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (scope_id, ancestor_artifact_id, descendant_artifact_id),
        CHECK (ancestor_artifact_id <> descendant_artifact_id),
        FOREIGN KEY (scope_id, ancestor_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id),
        FOREIGN KEY (scope_id, descendant_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id)
    );

    CREATE UNIQUE INDEX artifact_derivation_paths_unordered_pair_key
        ON corpus.artifact_derivation_paths(
            scope_id,
            LEAST(ancestor_artifact_id, descendant_artifact_id),
            GREATEST(ancestor_artifact_id, descendant_artifact_id)
        );

    CREATE FUNCTION corpus.record_derived_artifact_paths()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.parent_derived_artifact_id IS NULL THEN
            RETURN NEW;
        END IF;

        INSERT INTO corpus.artifact_derivation_paths (
            scope_id,
            ancestor_artifact_id,
            descendant_artifact_id
        )
        SELECT NEW.scope_id, ancestors.id, descendants.id
        FROM (
            SELECT NEW.parent_derived_artifact_id AS id
            UNION
            SELECT path.ancestor_artifact_id
            FROM corpus.artifact_derivation_paths path
            WHERE path.scope_id = NEW.scope_id
              AND path.descendant_artifact_id = NEW.parent_derived_artifact_id
        ) AS ancestors
        CROSS JOIN (
            SELECT NEW.derived_artifact_id AS id
            UNION
            SELECT path.descendant_artifact_id
            FROM corpus.artifact_derivation_paths path
            WHERE path.scope_id = NEW.scope_id
              AND path.ancestor_artifact_id = NEW.derived_artifact_id
        ) AS descendants
        ON CONFLICT (
            scope_id,
            ancestor_artifact_id,
            descendant_artifact_id
        ) DO NOTHING;

        RETURN NEW;
    EXCEPTION
        WHEN unique_violation OR check_violation THEN
            RAISE EXCEPTION 'derived artifact lineage cannot contain cycles'
                USING ERRCODE='23514';
    END $$;

    CREATE TRIGGER artifact_derivations_record_paths
    AFTER INSERT ON corpus.artifact_derivations
    FOR EACH ROW EXECUTE FUNCTION corpus.record_derived_artifact_paths();

    CREATE TABLE corpus.normalization_runs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
            REFERENCES corpus.scopes(id),
        input_manifest_locator text NOT NULL CHECK (btrim(input_manifest_locator) <> ''),
        input_manifest_sha256 text NOT NULL CHECK (input_manifest_sha256 ~ '^[0-9a-f]{64}$'),
        pipeline_version text NOT NULL CHECK (btrim(pipeline_version) <> ''),
        config_sha256 text NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
        status text NOT NULL DEFAULT 'queued'
            CHECK (status IN (
                'queued','running','reconciling','succeeded',\n                'completed_with_errors','failed','cancelled'
            )),
        requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        started_at timestamptz,
        finished_at timestamptz,
        selected_count integer NOT NULL DEFAULT 0 CHECK (selected_count >= 0),
        normalized_count integer NOT NULL DEFAULT 0 CHECK (normalized_count >= 0),
        review_required_count integer NOT NULL DEFAULT 0 CHECK (review_required_count >= 0),
        failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
        skipped_count integer NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
        UNIQUE (scope_id, id)
    );

    CREATE TABLE corpus.normalization_run_items (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
            REFERENCES corpus.scopes(id),
        run_id uuid NOT NULL,
        source_artifact_id uuid NOT NULL,
        status text NOT NULL DEFAULT 'pending'
            CHECK (status IN (
                'pending','running','normalized','quality_review_required','failed','skipped'
            )),
        normalized_artifact_id uuid,
        ocr_artifact_id uuid,
        error_code text,
        error_message text,
        quality_summary jsonb NOT NULL DEFAULT '{}'::jsonb
            CHECK (jsonb_typeof(quality_summary) = 'object'),
        started_at timestamptz,
        finished_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (scope_id, id),
        UNIQUE (scope_id, run_id, source_artifact_id),
        CHECK (status <> 'normalized' OR normalized_artifact_id IS NOT NULL),
        CHECK ((error_code IS NULL) = (error_message IS NULL)),
        CHECK (
            normalized_artifact_id IS NULL OR ocr_artifact_id IS NULL
            OR normalized_artifact_id <> ocr_artifact_id
        ),
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
        FOREIGN KEY (scope_id, run_id)
            REFERENCES corpus.normalization_runs(scope_id, id) ON DELETE CASCADE,
        FOREIGN KEY (scope_id, source_artifact_id)
            REFERENCES corpus.source_artifacts(scope_id, id),
        FOREIGN KEY (scope_id, normalized_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id),
        FOREIGN KEY (scope_id, ocr_artifact_id)
            REFERENCES corpus.derived_artifacts(scope_id, id)
    );

    CREATE INDEX artifact_derivations_source_idx
        ON corpus.artifact_derivations(scope_id, source_artifact_id, created_at DESC)
        WHERE source_artifact_id IS NOT NULL;
    CREATE INDEX artifact_derivations_parent_idx
        ON corpus.artifact_derivations(scope_id, parent_derived_artifact_id, created_at DESC)
        WHERE parent_derived_artifact_id IS NOT NULL;
    CREATE INDEX normalization_runs_manifest_idx
        ON corpus.normalization_runs(scope_id, input_manifest_sha256, requested_at DESC);
    CREATE INDEX normalization_run_items_run_status_idx
        ON corpus.normalization_run_items(scope_id, run_id, status);

    CREATE FUNCTION corpus.reject_immutable_normalization_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE='55000';
    END $$;

    CREATE TRIGGER derived_artifacts_immutable
    BEFORE UPDATE OR DELETE ON corpus.derived_artifacts
    FOR EACH ROW EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();

    CREATE TRIGGER artifact_derivations_immutable
    BEFORE UPDATE OR DELETE ON corpus.artifact_derivations
    FOR EACH ROW EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();

    CREATE TRIGGER artifact_derivation_paths_immutable
    BEFORE UPDATE OR DELETE ON corpus.artifact_derivation_paths
    FOR EACH ROW EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();
    """)


def downgrade() -> None:
    raise RuntimeError("Normalization provenance is intentionally non-destructive.")
