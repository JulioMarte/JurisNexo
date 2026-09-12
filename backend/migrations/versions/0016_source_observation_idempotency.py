"""Make source observations idempotent when no artifact URL exists.

Revision ID: 0016_source_observation_idempotency
Revises: 0015_source_inventory
Create Date: 2026-09-12

PostgreSQL unique constraints treat NULL values as distinct by default. That means
an unchanged metadata-only source record with document_url=NULL would create a new
observation on every reconciliation run. The source ledger is intended to append
only distinct source states, so NULL document URLs must compare as equal here.
"""

from alembic import op

revision = "0016_source_observation_idempotency"
down_revision = "0015_source_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.source_document_observations
        DROP CONSTRAINT source_document_observations_identity_key
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.source_document_observations
        ADD CONSTRAINT source_document_observations_identity_key
        UNIQUE NULLS NOT DISTINCT (
            source_document_id,
            payload_sha256,
            artifact_availability,
            document_url
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.source_document_observations
        DROP CONSTRAINT source_document_observations_identity_key
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.source_document_observations
        ADD CONSTRAINT source_document_observations_identity_key
        UNIQUE (
            source_document_id,
            payload_sha256,
            artifact_availability,
            document_url
        )
        """
    )
