"""Harden legal-instrument temporal identity constraints.

Revision ID: 0023_harden_legal_instrument_temporal
Revises: 0022_legal_instrument_temporal
Create Date: 2026-09-16

A version may derive only from another version of the same instrument. This is an
identity boundary, so invalid cross-instrument ancestry must fail immediately.
"""

from alembic import op

revision = "0023_harden_legal_instrument_temporal"
down_revision = "0022_legal_instrument_temporal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.legal_instrument_versions
            ALTER CONSTRAINT legal_instrument_versions_same_instrument_parent_fkey
            NOT DEFERRABLE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.legal_instrument_versions
            ALTER CONSTRAINT legal_instrument_versions_same_instrument_parent_fkey
            DEFERRABLE INITIALLY DEFERRED
        """
    )
