"""Preserve historical artifact-location provenance.

Revision ID: 0011_artifact_location_history
Revises: 0010_same_scope_provenance
Create Date: 2026-09-12

A locator such as an official URL can legitimately serve different bytes over
time. The original uniqueness rule treated the locator itself as identity and
therefore could not preserve that history. Artifact identity remains SHA-256;
locations record where each immutable artifact was observed.
"""

from alembic import op

revision = "0011_artifact_location_history"
down_revision = "0010_same_scope_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "ADD COLUMN source_registry_id uuid REFERENCES corpus.source_registries(id), "
        "ADD COLUMN discovered_via text"
    )
    op.execute(
        """
        UPDATE corpus.source_artifact_locations location
        SET source_registry_id = artifact.source_registry_id
        FROM corpus.source_artifacts artifact
        WHERE artifact.id = location.artifact_id
          AND location.source_registry_id IS NULL
        """
    )

    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP CONSTRAINT source_artifact_locations_locator_type_locator_key"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "ADD CONSTRAINT source_artifact_locations_artifact_locator_key "
        "UNIQUE (artifact_id, locator_type, locator)"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "ADD CONSTRAINT source_artifact_locations_seen_range_check "
        "CHECK (last_seen_at >= first_seen_at)"
    )
    op.execute(
        "CREATE INDEX source_artifact_locations_locator_history_idx "
        "ON corpus.source_artifact_locations (locator_type, locator, last_seen_at DESC)"
    )
    op.execute(
        "CREATE INDEX source_artifact_locations_registry_idx "
        "ON corpus.source_artifact_locations (source_registry_id) "
        "WHERE source_registry_id IS NOT NULL"
    )

    op.execute(
        """
        COMMENT ON COLUMN corpus.source_artifact_locations.source_registry_id IS
        'Source registry that exposed this locator. Location-level source identity allows identical bytes to be observed by multiple official registries.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.source_artifact_locations.discovered_via IS
        'Official listing, result, or detail URL from which this artifact locator was discovered; it is provenance, not artifact identity.'
        """
    )
    op.execute(
        """
        COMMENT ON CONSTRAINT source_artifact_locations_artifact_locator_key
        ON corpus.source_artifact_locations IS
        'The same locator may point to different immutable artifacts over time; uniqueness applies only within one artifact.'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS corpus.source_artifact_locations_registry_idx")
    op.execute(
        "DROP INDEX IF EXISTS corpus.source_artifact_locations_locator_history_idx"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP CONSTRAINT IF EXISTS source_artifact_locations_seen_range_check"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP CONSTRAINT IF EXISTS source_artifact_locations_artifact_locator_key"
    )
    op.execute(
        """
        DELETE FROM corpus.source_artifact_locations newer
        USING corpus.source_artifact_locations older
        WHERE newer.id <> older.id
          AND newer.locator_type = older.locator_type
          AND newer.locator = older.locator
          AND (
              newer.last_seen_at < older.last_seen_at
              OR (newer.last_seen_at = older.last_seen_at AND newer.id < older.id)
          )
        """
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "ADD CONSTRAINT source_artifact_locations_locator_type_locator_key "
        "UNIQUE (locator_type, locator)"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP COLUMN discovered_via, "
        "DROP COLUMN source_registry_id"
    )
