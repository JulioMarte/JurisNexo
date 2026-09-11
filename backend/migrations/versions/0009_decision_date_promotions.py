"""Add auditable decision-date promotion events.

Revision ID: 0009_decision_date_promotions
Revises: 0008_quarantine_legacy_public
Create Date: 2026-09-11
"""

from alembic import op

revision = "0009_decision_date_promotions"
down_revision = "0008_quarantine_legacy_public"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.case_metadata_promotions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            resolution_id uuid NOT NULL,
            field_name text NOT NULL,
            previous_date date,
            promoted_date date NOT NULL,
            previous_status text NOT NULL,
            promoted_status text NOT NULL,
            promotion_method text NOT NULL,
            code_revision text NOT NULL,
            idempotency_key text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT case_metadata_promotions_resolution_same_case_fkey
                FOREIGN KEY (case_id, resolution_id)
                REFERENCES corpus.case_metadata_resolutions (case_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT case_metadata_promotions_field_check
                CHECK (field_name = 'decision_date'),
            CONSTRAINT case_metadata_promotions_previous_status_check
                CHECK (previous_status IN (
                    'verified_primary_text',
                    'verified_official_metadata',
                    'parsed_high_confidence',
                    'parsed_unverified',
                    'conflicting',
                    'unknown'
                )),
            CONSTRAINT case_metadata_promotions_promoted_status_check
                CHECK (promoted_status IN (
                    'verified_primary_text',
                    'verified_official_metadata',
                    'parsed_high_confidence'
                )),
            CONSTRAINT case_metadata_promotions_method_check
                CHECK (promotion_method IN (
                    'automatic_reconciler',
                    'manual_review',
                    'official_metadata_import'
                )),
            CONSTRAINT case_metadata_promotions_code_revision_check
                CHECK (btrim(code_revision) <> ''),
            CONSTRAINT case_metadata_promotions_idempotency_key_check
                CHECK (idempotency_key ~ '^[0-9a-f]{64}$')
        )
        """
    )

    op.execute(
        "CREATE INDEX case_metadata_promotions_case_created_idx "
        "ON corpus.case_metadata_promotions (case_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX case_metadata_promotions_case_resolution_idx "
        "ON corpus.case_metadata_promotions (case_id, resolution_id)"
    )

    op.execute(
        "ALTER TABLE corpus.cases "
        "ADD COLUMN decision_date_resolution_id uuid"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "ADD CONSTRAINT cases_decision_date_resolution_same_case_fkey "
        "FOREIGN KEY (id, decision_date_resolution_id) "
        "REFERENCES corpus.case_metadata_resolutions (case_id, id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "CREATE INDEX cases_decision_date_resolution_idx "
        "ON corpus.cases (decision_date_resolution_id) "
        "WHERE decision_date_resolution_id IS NOT NULL"
    )

    # Cross-table semantic checks belong in a trigger because a CHECK constraint
    # cannot inspect the linked resolution or selected evidence observation.
    op.execute(
        """
        CREATE FUNCTION corpus.validate_decision_date_promotion()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog, corpus
        AS $function$
        DECLARE
            resolved_field text;
            resolved_type text;
            resolved_date_value date;
            resolved_status text;
        BEGIN
            SELECT field_name, value_type, resolved_date, resolution_status
            INTO resolved_field, resolved_type, resolved_date_value, resolved_status
            FROM corpus.case_metadata_resolutions
            WHERE id = NEW.resolution_id
              AND case_id = NEW.case_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'resolution does not belong to promotion case';
            END IF;

            IF resolved_field <> 'decision_date' OR resolved_type <> 'date' THEN
                RAISE EXCEPTION 'resolution is not a decision_date resolution';
            END IF;

            IF resolved_status NOT IN (
                'verified_primary_text',
                'verified_official_metadata',
                'parsed_high_confidence'
            ) THEN
                RAISE EXCEPTION 'resolution status % is not eligible for automatic canonical promotion', resolved_status;
            END IF;

            IF resolved_date_value IS DISTINCT FROM NEW.promoted_date
               OR resolved_status IS DISTINCT FROM NEW.promoted_status THEN
                RAISE EXCEPTION 'promotion snapshot does not match linked resolution';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM corpus.case_metadata_resolution_observations AS link
                JOIN corpus.case_metadata_observations AS observation
                  ON observation.id = link.observation_id
                 AND observation.case_id = link.case_id
                WHERE link.resolution_id = NEW.resolution_id
                  AND link.case_id = NEW.case_id
                  AND link.role = 'selected'
                  AND observation.evidence_case_page_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'eligible promotion requires selected page-level evidence';
            END IF;

            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER case_metadata_promotions_validate
        BEFORE INSERT ON corpus.case_metadata_promotions
        FOR EACH ROW EXECUTE FUNCTION corpus.validate_decision_date_promotion()
        """
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.case_metadata_promotions IS
        'Append-only-in-practice audit events recording when an eligible metadata resolution becomes canonical case state.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.decision_date_resolution_id IS
        'Resolution currently supporting canonical decision_date. Same-case composite FK prevents provenance drift.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS case_metadata_promotions_validate ON corpus.case_metadata_promotions")
    op.execute("DROP FUNCTION IF EXISTS corpus.validate_decision_date_promotion()")
    op.execute("DROP INDEX IF EXISTS corpus.cases_decision_date_resolution_idx")
    op.execute(
        "ALTER TABLE corpus.cases "
        "DROP CONSTRAINT IF EXISTS cases_decision_date_resolution_same_case_fkey"
    )
    op.execute("ALTER TABLE corpus.cases DROP COLUMN IF EXISTS decision_date_resolution_id")
    op.execute("DROP TABLE IF EXISTS corpus.case_metadata_promotions")
