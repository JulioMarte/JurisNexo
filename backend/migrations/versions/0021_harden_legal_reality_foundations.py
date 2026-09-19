"""Harden legal-reality scope and evidence constraints.

Revision ID: 0021_harden_legal_reality
Revises: 0020_legal_reality
Create Date: 2026-09-16

The foundation migration intentionally introduced the new identities first. This
follow-up makes tenant/corpus scope violations fail immediately and closes a
nullable composite-FK hole in proposition evidence.
"""

from alembic import op

revision = "0021_harden_legal_reality"
down_revision = "0020_legal_reality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.legal_proceedings
            ALTER CONSTRAINT legal_proceedings_same_scope_controversy_fkey
            NOT DEFERRABLE
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_proposition_evidence
        ADD CONSTRAINT legal_proposition_evidence_case_page_shape_check
        CHECK (case_page_id IS NULL OR source_case_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.legal_proposition_evidence
        DROP CONSTRAINT IF EXISTS legal_proposition_evidence_case_page_shape_check
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_proceedings
            ALTER CONSTRAINT legal_proceedings_same_scope_controversy_fkey
            DEFERRABLE INITIALLY DEFERRED
        """
    )
