"""Add a generic canonical legal-document layer.

Revision ID: 0012_generic_legal_documents
Revises: 0011_artifact_location_history
Create Date: 2026-09-12

The acquisition/provenance layer is source-neutral, but the original canonical
model was centered on judicial cases. This migration adds a provider-neutral,
document-type-neutral legal layer so statutes, decrees, regulations,
administrative resolutions, circulars, gazettes, treaties and judicial
decisions can share the same immutable artifact/provenance contract without
being forced into corpus.cases.
"""

from alembic import op

revision = "0012_generic_legal_documents"
down_revision = "0011_artifact_location_history"
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
        CREATE TABLE corpus.legal_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            document_type text NOT NULL,
            country_code character(2) NOT NULL DEFAULT 'DO',
            jurisdiction_code text,
            issuing_authority text,
            title text,
            document_number text,
            document_date date,
            effective_from date,
            effective_to date,
            language text NOT NULL DEFAULT 'es',
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            quality_status text NOT NULL DEFAULT 'unreviewed',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_documents_type_check CHECK (
                document_type = ANY (ARRAY[
                    'judicial_decision',
                    'constitution',
                    'statute',
                    'decree',
                    'regulation',
                    'administrative_resolution',
                    'circular',
                    'gazette',
                    'treaty',
                    'opinion',
                    'order',
                    'other'
                ]::text[])
            ),
            CONSTRAINT legal_documents_country_code_check CHECK (country_code ~ '^[A-Z]{2}$'),
            CONSTRAINT legal_documents_identity_status_check CHECK (
                identity_status = ANY (ARRAY[
                    'canonical',
                    'probable_duplicate',
                    'identity_unresolved',
                    'merged_with_canonical'
                ]::text[])
            ),
            CONSTRAINT legal_documents_quality_status_check CHECK (
                quality_status = ANY (ARRAY[
                    'unreviewed',
                    'searchable',
                    'quality_review_required',
                    'blocked'
                ]::text[])
            ),
            CONSTRAINT legal_documents_effective_range_check CHECK (
                effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT legal_documents_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_documents_type_date_idx "
        "ON corpus.legal_documents (document_type, document_date DESC)"
    )
    op.execute(
        "CREATE INDEX legal_documents_number_idx "
        "ON corpus.legal_documents (document_number) WHERE document_number IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_document_identifiers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid NOT NULL REFERENCES corpus.legal_documents(id),
            identifier_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_value text,
            source_registry_id uuid REFERENCES corpus.source_registries(id),
            is_primary boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_document_identifiers_type_nonempty CHECK (btrim(identifier_type) <> ''),
            CONSTRAINT legal_document_identifiers_raw_nonempty CHECK (btrim(raw_value) <> ''),
            CONSTRAINT legal_document_identifiers_unique UNIQUE (
                document_id, identifier_type, raw_value, source_registry_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_document_identifiers_lookup_idx "
        "ON corpus.legal_document_identifiers (identifier_type, normalized_value) "
        "WHERE normalized_value IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_document_artifact_occurrences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid NOT NULL,
            artifact_id uuid NOT NULL,
            scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid,
            occurrence_kind text NOT NULL DEFAULT 'whole_artifact',
            start_page integer,
            end_page integer,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL DEFAULT 'deterministic_source_mapping',
            verification_confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_document_occurrence_kind_check CHECK (
                occurrence_kind = ANY (ARRAY['whole_artifact', 'page_range']::text[])
            ),
            CONSTRAINT legal_document_occurrence_pages_check CHECK (
                (occurrence_kind = 'whole_artifact' AND start_page IS NULL AND end_page IS NULL)
                OR
                (occurrence_kind = 'page_range' AND start_page > 0 AND end_page >= start_page)
            ),
            CONSTRAINT legal_document_occurrence_status_check CHECK (
                verification_status = ANY (ARRAY['candidate', 'verified', 'ambiguous', 'rejected']::text[])
            ),
            CONSTRAINT legal_document_occurrence_confidence_check CHECK (
                verification_confidence IS NULL
                OR (verification_confidence >= 0 AND verification_confidence <= 1)
            ),
            CONSTRAINT legal_document_occurrence_same_scope_document_fkey
                FOREIGN KEY (scope_id, document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_document_occurrence_same_scope_artifact_fkey
                FOREIGN KEY (scope_id, artifact_id)
                REFERENCES corpus.source_artifacts(scope_id, id),
            CONSTRAINT legal_document_occurrence_unique UNIQUE (
                document_id, artifact_id, occurrence_kind, start_page, end_page
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_document_occurrence_artifact_idx "
        "ON corpus.legal_document_artifact_occurrences (artifact_id)"
    )

    op.execute(
        "ALTER TABLE corpus.cases ADD COLUMN legal_document_id uuid UNIQUE "
        "REFERENCES corpus.legal_documents(id)"
    )

    op.execute(
        """
        COMMENT ON COLUMN corpus.source_artifact_locations.source_collection IS
        'Source-native or normalized collection such as decisions, historical-decisions, bulletins, gazettes, statutes, or regulations. It is routing/classification metadata, never artifact identity.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_documents IS
        'Canonical legal-document superclass for judicial and non-judicial material. Source bytes remain immutable in source_artifacts; this table represents the legal work embodied by those bytes.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_document_artifact_occurrences IS
        'Maps one canonical legal document to the exact immutable source artifact or page range in which it appears.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.legal_document_id IS
        'Optional judicial specialization link. Existing case workflows remain compatible while new canonical material can use legal_documents directly.'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE corpus.cases DROP COLUMN IF EXISTS legal_document_id")
    op.execute("DROP TABLE IF EXISTS corpus.legal_document_artifact_occurrences")
    op.execute("DROP TABLE IF EXISTS corpus.legal_document_identifiers")
    op.execute("DROP TABLE IF EXISTS corpus.legal_documents")
    op.execute("DROP INDEX IF EXISTS corpus.source_artifact_locations_collection_idx")
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations "
        "DROP CONSTRAINT IF EXISTS source_artifact_locations_collection_check"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifact_locations DROP COLUMN IF EXISTS source_collection"
    )
