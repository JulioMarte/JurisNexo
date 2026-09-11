"""Add auditable case metadata resolution ledger.

Revision ID: 0007_resolution_ledger
Revises: 0006_ingestion_artifact_prov
Create Date: 2026-09-11
"""

from alembic import op

revision = "0007_resolution_ledger"
down_revision = "0006_ingestion_artifact_prov"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite identity is required so the resolution-observation join can prove
    # that every linked observation belongs to the same canonical case.
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ADD CONSTRAINT case_metadata_observations_case_id_id_key "
        "UNIQUE (case_id, id)"
    )

    op.execute(
        """
        CREATE TABLE corpus.case_metadata_resolutions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            field_name text NOT NULL,
            value_type text NOT NULL,
            resolved_text text,
            resolved_date date,
            resolved_json jsonb,
            resolution_status text NOT NULL,
            resolver_name text NOT NULL,
            resolver_version text NOT NULL,
            code_revision text NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (case_id, id),
            CONSTRAINT case_metadata_resolutions_field_name_check
                CHECK (btrim(field_name) <> ''),
            CONSTRAINT case_metadata_resolutions_value_type_check
                CHECK (value_type IN ('text', 'date', 'identifier', 'json')),
            CONSTRAINT case_metadata_resolutions_status_check
                CHECK (resolution_status IN (
                    'verified_primary_text',
                    'verified_official_metadata',
                    'parsed_high_confidence',
                    'parsed_unverified',
                    'conflicting',
                    'unknown'
                )),
            CONSTRAINT case_metadata_resolutions_resolver_name_check
                CHECK (btrim(resolver_name) <> ''),
            CONSTRAINT case_metadata_resolutions_resolver_version_check
                CHECK (btrim(resolver_version) <> ''),
            CONSTRAINT case_metadata_resolutions_code_revision_check
                CHECK (btrim(code_revision) <> ''),
            CONSTRAINT case_metadata_resolutions_idempotency_key_check
                CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
            CONSTRAINT case_metadata_resolutions_normalized_shape_check
                CHECK (
                    (value_type = 'date' AND resolved_text IS NULL AND resolved_json IS NULL)
                    OR (
                        value_type IN ('text', 'identifier')
                        AND resolved_date IS NULL
                        AND resolved_json IS NULL
                    )
                    OR (
                        value_type = 'json'
                        AND resolved_text IS NULL
                        AND resolved_date IS NULL
                    )
                ),
            CONSTRAINT case_metadata_resolutions_status_value_check
                CHECK (
                    (
                        resolution_status IN ('conflicting', 'unknown')
                        AND num_nonnulls(resolved_text, resolved_date, resolved_json) = 0
                    )
                    OR (
                        resolution_status NOT IN ('conflicting', 'unknown')
                        AND num_nonnulls(resolved_text, resolved_date, resolved_json) = 1
                    )
                )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.case_metadata_resolution_observations (
            resolution_id uuid NOT NULL,
            case_id uuid NOT NULL,
            observation_id uuid NOT NULL,
            role text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (resolution_id, observation_id),
            CONSTRAINT case_metadata_resolution_observations_role_check
                CHECK (role IN ('supporting', 'conflicting', 'selected')),
            CONSTRAINT case_metadata_resolution_observations_resolution_same_case_fkey
                FOREIGN KEY (case_id, resolution_id)
                REFERENCES corpus.case_metadata_resolutions (case_id, id)
                ON DELETE CASCADE,
            CONSTRAINT case_metadata_resolution_observations_observation_same_case_fkey
                FOREIGN KEY (case_id, observation_id)
                REFERENCES corpus.case_metadata_observations (case_id, id)
                ON DELETE RESTRICT
        )
        """
    )

    op.execute(
        "CREATE INDEX case_metadata_resolutions_case_field_created_idx "
        "ON corpus.case_metadata_resolutions (case_id, field_name, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX case_metadata_resolutions_status_idx "
        "ON corpus.case_metadata_resolutions (resolution_status)"
    )
    op.execute(
        "CREATE INDEX case_metadata_resolution_observations_case_resolution_idx "
        "ON corpus.case_metadata_resolution_observations (case_id, resolution_id)"
    )
    op.execute(
        "CREATE INDEX case_metadata_resolution_observations_case_observation_idx "
        "ON corpus.case_metadata_resolution_observations (case_id, observation_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX case_metadata_resolution_one_selected_idx "
        "ON corpus.case_metadata_resolution_observations (resolution_id) "
        "WHERE role = 'selected'"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.case_metadata_resolutions IS
        'Immutable-in-practice resolver output between raw observations and canonical case metadata. Promotion is recorded separately and must not mutate this row.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.case_metadata_resolution_observations IS
        'Exact observation set considered by one metadata resolution, including supporting, conflicting, and selected evidence.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.case_metadata_resolution_observations")
    op.execute("DROP TABLE IF EXISTS corpus.case_metadata_resolutions")
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "DROP CONSTRAINT case_metadata_observations_case_id_id_key"
    )
