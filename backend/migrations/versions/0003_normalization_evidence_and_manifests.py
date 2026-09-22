"""Add normalization evidence, model calls, corrections and run manifests.

Revision ID: 0003_normalization_evidence
Revises: 0002_normalization_control
Create Date: 2026-09-21
"""

from alembic import op

revision = "0003_normalization_evidence"
down_revision = "0002_normalization_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.normalization_model_calls (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL
                DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            run_id uuid NOT NULL,
            purpose text NOT NULL
                CHECK (purpose IN (
                    'text_quality_judge',
                    'claim_verification',
                    'visual_verification'
                )),
            provider text NOT NULL CHECK (btrim(provider) <> ''),
            model text NOT NULL CHECK (btrim(model) <> ''),
            model_version text,
            response_id text,
            estimated_input_tokens integer
                CHECK (
                    estimated_input_tokens IS NULL
                    OR estimated_input_tokens >= 0
                ),
            input_tokens integer
                CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens integer
                CHECK (output_tokens IS NULL OR output_tokens >= 0),
            total_tokens integer
                CHECK (total_tokens IS NULL OR total_tokens >= 0),
            cost_usd numeric(18,8)
                CHECK (cost_usd IS NULL OR cost_usd >= 0),
            latency_ms integer
                CHECK (latency_ms IS NULL OR latency_ms >= 0),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(metadata) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_id, id),
            FOREIGN KEY (scope_id, run_id)
                REFERENCES corpus.normalization_runs(scope_id, id)
                ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX normalization_model_calls_provider_response_key
            ON corpus.normalization_model_calls(scope_id, provider, response_id)
            WHERE response_id IS NOT NULL;

        CREATE TABLE corpus.normalization_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL
                DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            run_item_id uuid NOT NULL,
            artifact_id uuid,
            model_call_id uuid,
            observation_kind text NOT NULL
                CHECK (observation_kind IN (
                    'native_text',
                    'ocr_text',
                    'deterministic_qa',
                    'text_quality_judge',
                    'visual_verification',
                    'human_review',
                    'sentinel_selection',
                    'reuse_validation'
                )),
            page_index integer CHECK (page_index IS NULL OR page_index >= 0),
            locator jsonb NOT NULL DEFAULT '{}'::jsonb
                CHECK (jsonb_typeof(locator) = 'object'),
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            status text NOT NULL DEFAULT 'candidate'
                CHECK (
                    status IN (
                        'candidate',
                        'accepted',
                        'rejected',
                        'unresolved'
                    )
                ),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_id, id),
            FOREIGN KEY (scope_id, run_item_id)
                REFERENCES corpus.normalization_run_items(scope_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (scope_id, artifact_id)
                REFERENCES corpus.derived_artifacts(scope_id, id),
            FOREIGN KEY (scope_id, model_call_id)
                REFERENCES corpus.normalization_model_calls(scope_id, id)
        );

        CREATE TABLE corpus.normalization_corrections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL
                DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            observation_id uuid NOT NULL,
            verifier_observation_id uuid,
            replacement_text text NOT NULL,
            rationale text,
            status text NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed','accepted','rejected')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_id, id),
            FOREIGN KEY (scope_id, observation_id)
                REFERENCES corpus.normalization_observations(scope_id, id),
            FOREIGN KEY (scope_id, verifier_observation_id)
                REFERENCES corpus.normalization_observations(scope_id, id),
            CHECK (
                verifier_observation_id IS NULL
                OR verifier_observation_id <> observation_id
            )
        );

        CREATE UNIQUE INDEX normalization_one_accepted_correction_per_observation
            ON corpus.normalization_corrections(scope_id, observation_id)
            WHERE status = 'accepted';

        CREATE TABLE corpus.normalization_manifests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL
                DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            run_id uuid NOT NULL,
            sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            storage_locator text NOT NULL UNIQUE
                CHECK (btrim(storage_locator) <> ''),
            byte_size bigint NOT NULL CHECK (byte_size >= 0),
            selected_count integer NOT NULL CHECK (selected_count >= 0),
            normalized_count integer NOT NULL CHECK (normalized_count >= 0),
            review_required_count integer NOT NULL
                CHECK (review_required_count >= 0),
            failed_count integer NOT NULL CHECK (failed_count >= 0),
            skipped_count integer NOT NULL CHECK (skipped_count >= 0),
            published_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_id, id),
            UNIQUE (scope_id, run_id),
            FOREIGN KEY (scope_id, run_id)
                REFERENCES corpus.normalization_runs(scope_id, id)
        );

        CREATE INDEX normalization_model_calls_run_idx
            ON corpus.normalization_model_calls(
                scope_id, run_id, purpose, created_at
            );
        CREATE INDEX normalization_observations_run_item_idx
            ON corpus.normalization_observations(
                scope_id, run_item_id, observation_kind, created_at
            );
        CREATE INDEX normalization_observations_artifact_idx
            ON corpus.normalization_observations(scope_id, artifact_id)
            WHERE artifact_id IS NOT NULL;
        CREATE INDEX normalization_observations_model_call_idx
            ON corpus.normalization_observations(scope_id, model_call_id)
            WHERE model_call_id IS NOT NULL;

        CREATE TRIGGER normalization_model_calls_immutable
        BEFORE UPDATE OR DELETE ON corpus.normalization_model_calls
        FOR EACH ROW
        EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();

        CREATE TRIGGER normalization_observations_immutable
        BEFORE UPDATE OR DELETE ON corpus.normalization_observations
        FOR EACH ROW
        EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();

        CREATE TRIGGER normalization_corrections_immutable
        BEFORE UPDATE OR DELETE ON corpus.normalization_corrections
        FOR EACH ROW
        EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();

        CREATE TRIGGER normalization_manifests_immutable
        BEFORE UPDATE OR DELETE ON corpus.normalization_manifests
        FOR EACH ROW
        EXECUTE FUNCTION corpus.reject_immutable_normalization_mutation();
        """
    )


def downgrade() -> None:
    raise RuntimeError("Normalization evidence is intentionally non-destructive.")
