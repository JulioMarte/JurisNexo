"""Bind judicial treatments to first-class legal issues.

Revision ID: 0047_treatment_legal_issues
Revises: 0046_v4_hardening
Create Date: 2026-09-18

Legal Reality V4 makes a legal question an identity distinct from a legal
proposition. Judicial treatment therefore cannot keep using the legacy
issue_proposition_id compatibility shape. This migration moves contextual
judicial treatments to legal_issue_id and updates temporal uniqueness/overlap
guards accordingly.
"""

from alembic import op

revision = "0047_treatment_legal_issues"
down_revision = "0046_v4_hardening"
branch_labels = None
depends_on = None

ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions ADD COLUMN legal_issue_id uuid"
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_treatment_assertions
        ADD CONSTRAINT legal_treatment_assertions_same_scope_issue_v4_fkey
        FOREIGN KEY (scope_id,legal_issue_id)
        REFERENCES corpus.legal_issues(scope_id,id)
        """
    )

    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions "
        "DROP CONSTRAINT IF EXISTS legal_treatment_assertions_context_check"
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_treatment_assertions
        ADD CONSTRAINT legal_treatment_assertions_context_check CHECK (
            treatment_type IN ('cites','references') OR legal_issue_id IS NOT NULL
        )
        """
    )

    op.execute(
        "DROP INDEX IF EXISTS corpus.legal_treatment_assertions_current_idx"
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX legal_treatment_assertions_current_idx
        ON corpus.legal_treatment_assertions (
            source_case_id,
            target_case_id,
            treatment_type,
            coalesce(legal_issue_id, '{ZERO_UUID}'::uuid),
            coalesce(source_proposition_id, '{ZERO_UUID}'::uuid),
            coalesce(target_proposition_id, '{ZERO_UUID}'::uuid)
        )
        WHERE known_to IS NULL
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS legal_treatment_assertions_no_knowledge_overlap "
        "ON corpus.legal_treatment_assertions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS corpus.reject_treatment_knowledge_overlap()"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.reject_treatment_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':',NEW.source_case_id,NEW.target_case_id,
                    NEW.treatment_type,NEW.legal_issue_id,
                    NEW.source_proposition_id,NEW.target_proposition_id),
                4701
            ));
            IF EXISTS (
                SELECT 1
                FROM corpus.legal_treatment_assertions k
                WHERE k.id<>NEW.id
                  AND k.source_case_id=NEW.source_case_id
                  AND k.target_case_id=NEW.target_case_id
                  AND k.treatment_type=NEW.treatment_type
                  AND k.legal_issue_id IS NOT DISTINCT FROM NEW.legal_issue_id
                  AND k.source_proposition_id
                      IS NOT DISTINCT FROM NEW.source_proposition_id
                  AND k.target_proposition_id
                      IS NOT DISTINCT FROM NEW.target_proposition_id
                  AND tstzrange(k.known_from,k.known_to,'[)')
                      && tstzrange(NEW.known_from,NEW.known_to,'[)')
            ) THEN
                RAISE EXCEPTION
                    'overlapping judicial treatment knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_treatment_assertions_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.legal_treatment_assertions "
        "FOR EACH ROW EXECUTE FUNCTION corpus.reject_treatment_knowledge_overlap()"
    )

    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions "
        "DROP CONSTRAINT IF EXISTS legal_treatment_assertions_same_scope_issue_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions DROP COLUMN issue_proposition_id"
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.legal_treatment_assertions.legal_issue_id IS
        'First-class legal question that supplies doctrinal context for substantive judicial treatment. A legal issue is not a legal proposition.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_treatment_assertions IS
        'Contextual judicial treatment between decisions. Substantive treatment requires a first-class legal issue; source/target propositions may further identify the reasoning treated.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0047 removes the legacy issue-as-proposition treatment model and is intentionally non-destructive"
    )
