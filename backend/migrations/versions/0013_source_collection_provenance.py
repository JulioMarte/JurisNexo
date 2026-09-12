"""Persist source collection routing metadata.

Revision ID: 0013_source_collection_provenance
Revises: 0012_generic_legal_documents
Create Date: 2026-09-12

Collections distinguish source-native streams such as decisions,
historical-decisions and bulletins while SHA-256 remains artifact identity.
"""

from alembic import op

revision = "0013_source_collection_provenance"
down_revision = "0012_generic_legal_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations ADD COLUMN source_collection text"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "ADD CONSTRAINT source_artifact_locations_collection_check "
        "CHECK (source_collection IS NULL OR source_collection ~ '^[a-z0-9]+(-[a-z0-9]+)*$')"
    )
    op.execute(
        "CREATE INDEX source_artifact_locations_collection_idx "
        "ON corpus.source_artifact_locations (source_registry_id, source_collection) "
        "WHERE source_collection IS NOT NULL"
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.source_artifact_locations.source_collection IS
        'Source-native or normalized collection such as decisions, historical-decisions, bulletins, gazettes, statutes, or regulations. It is routing/classification metadata, never artifact identity.'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS corpus.source_artifact_locations_collection_idx")
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP CONSTRAINT IF EXISTS source_artifact_locations_collection_check"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations DROP COLUMN IF EXISTS source_collection"
    )
