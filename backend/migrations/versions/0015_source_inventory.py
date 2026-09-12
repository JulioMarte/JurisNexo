"""Add durable official-source document inventory.

Revision ID: 0015_source_inventory
Revises: 0014_legal_graph
Create Date: 2026-09-12

A source can publish a logical record before a downloadable artifact exists. This
revision preserves those source-level records and every distinct observed payload
without prematurely promoting them to canonical legal_documents.
"""

from alembic import op

revision = "0015_source_inventory"
down_revision = "0014_legal_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.source_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_registry_id uuid NOT NULL REFERENCES corpus.source_registries(id),
            source_identifier text NOT NULL,
            source_collection text NOT NULL,
            document_kind text NOT NULL,
            discovery_url text NOT NULL,
            current_document_url text,
            artifact_availability text NOT NULL DEFAULT 'unknown',
            latest_source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            latest_payload_sha256 text NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT source_documents_identifier_nonempty CHECK (btrim(source_identifier) <> ''),
            CONSTRAINT source_documents_collection_nonempty CHECK (btrim(source_collection) <> ''),
            CONSTRAINT source_documents_kind_nonempty CHECK (btrim(document_kind) <> ''),
            CONSTRAINT source_documents_discovery_https CHECK (discovery_url ~ '^https://'),
            CONSTRAINT source_documents_document_url_https CHECK (
                current_document_url IS NULL OR current_document_url ~ '^https://'
            ),
            CONSTRAINT source_documents_availability_check CHECK (
                artifact_availability IN ('available', 'not_published', 'unavailable', 'unknown')
            ),
            CONSTRAINT source_documents_payload_sha256_check CHECK (
                latest_payload_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT source_documents_seen_range_check CHECK (last_seen_at >= first_seen_at),
            CONSTRAINT source_documents_identity_key UNIQUE (
                source_registry_id, source_collection, source_identifier
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX source_documents_registry_collection_idx "
        "ON corpus.source_documents (source_registry_id, source_collection, artifact_availability)"
    )
    op.execute(
        "CREATE INDEX source_documents_current_url_idx "
        "ON corpus.source_documents (current_document_url) WHERE current_document_url IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.source_document_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id uuid NOT NULL REFERENCES corpus.source_documents(id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            discovery_url text NOT NULL,
            document_url text,
            artifact_availability text NOT NULL,
            source_payload jsonb NOT NULL,
            payload_sha256 text NOT NULL,
            normalization_notes jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT source_document_observations_discovery_https CHECK (discovery_url ~ '^https://'),
            CONSTRAINT source_document_observations_document_url_https CHECK (
                document_url IS NULL OR document_url ~ '^https://'
            ),
            CONSTRAINT source_document_observations_availability_check CHECK (
                artifact_availability IN ('available', 'not_published', 'unavailable', 'unknown')
            ),
            CONSTRAINT source_document_observations_payload_sha256_check CHECK (
                payload_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT source_document_observations_identity_key UNIQUE (
                source_document_id, payload_sha256, artifact_availability, document_url
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX source_document_observations_document_time_idx "
        "ON corpus.source_document_observations (source_document_id, observed_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE corpus.source_document_artifacts (
            source_document_id uuid NOT NULL REFERENCES corpus.source_documents(id) ON DELETE CASCADE,
            artifact_id uuid NOT NULL REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE,
            relationship_type text NOT NULL DEFAULT 'primary',
            first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (source_document_id, artifact_id, relationship_type),
            CONSTRAINT source_document_artifacts_relationship_check CHECK (
                relationship_type IN ('primary', 'attachment', 'replacement', 'supplement', 'scan', 'transcription')
            ),
            CONSTRAINT source_document_artifacts_seen_range_check CHECK (last_seen_at >= first_seen_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX source_document_artifacts_artifact_idx "
        "ON corpus.source_document_artifacts (artifact_id)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.source_documents IS
        'Logical records published by an external source. They may exist before any downloadable artifact and are not automatically canonical legal_documents.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.source_document_observations IS
        'Append-only distinct source payload observations preserving official metadata and deterministic normalization notes.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.source_document_artifacts IS
        'Links source-level logical publications to immutable acquired artifacts without conflating source identity with content identity.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.source_document_artifacts")
    op.execute("DROP TABLE IF EXISTS corpus.source_document_observations")
    op.execute("DROP TABLE IF EXISTS corpus.source_documents")
