"""Add stable legal-instrument and provision identities with temporal versions.

Revision ID: 0022_legal_instrument_temporal
Revises: 0021_harden_legal_reality
Create Date: 2026-09-16

A statute/code/regulation is not identical to one text snapshot, publication, or
consolidation. Likewise, a provision can persist while its label, location, and
text change. This migration models those identities separately and records
explicit lifecycle/amendment effects without rewriting source documents.
"""

from alembic import op

revision = "0022_legal_instrument_temporal"
down_revision = "0021_harden_legal_reality"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.legal_instruments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            instrument_type text NOT NULL,
            country_code character(2) NOT NULL DEFAULT 'DO',
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            canonical_title text,
            issuing_authority_raw text,
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instruments_type_check CHECK (
                instrument_type IN (
                    'constitution', 'code', 'statute', 'decree', 'regulation',
                    'administrative_resolution', 'circular', 'treaty',
                    'ordinance', 'rule', 'other'
                )
            ),
            CONSTRAINT legal_instruments_country_check CHECK (country_code ~ '^[A-Z]{{2}}$'),
            CONSTRAINT legal_instruments_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate',
                    'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT legal_instruments_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_instruments_lookup_idx "
        "ON corpus.legal_instruments (country_code, jurisdiction_code, instrument_type)"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_instrument_identifiers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            instrument_id uuid NOT NULL REFERENCES corpus.legal_instruments(id) ON DELETE CASCADE,
            identifier_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_value text,
            source_registry_id uuid REFERENCES corpus.source_registries(id),
            is_primary boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_identifiers_type_nonempty
                CHECK (btrim(identifier_type) <> ''),
            CONSTRAINT legal_instrument_identifiers_value_nonempty
                CHECK (btrim(raw_value) <> ''),
            CONSTRAINT legal_instrument_identifiers_unique
                UNIQUE NULLS NOT DISTINCT (
                    instrument_id, identifier_type, raw_value, source_registry_id
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_instrument_identifiers_lookup_idx "
        "ON corpus.legal_instrument_identifiers (identifier_type, normalized_value) "
        "WHERE normalized_value IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_instrument_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_id uuid NOT NULL,
            version_kind text NOT NULL,
            version_label text,
            valid_from date,
            valid_to date,
            version_status text NOT NULL DEFAULT 'candidate',
            derivation_method text NOT NULL,
            derived_from_version_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_versions_kind_check CHECK (
                version_kind IN (
                    'original', 'amended', 'official_consolidation',
                    'editorial_consolidation', 'corrected', 'historical_snapshot', 'other'
                )
            ),
            CONSTRAINT legal_instrument_versions_status_check CHECK (
                version_status IN ('candidate', 'verified', 'superseded', 'withdrawn')
            ),
            CONSTRAINT legal_instrument_versions_range_check CHECK (
                valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
            ),
            CONSTRAINT legal_instrument_versions_same_scope_instrument_fkey
                FOREIGN KEY (scope_id, instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_instrument_versions_scope_id_id_key UNIQUE (scope_id, id),
            CONSTRAINT legal_instrument_versions_instrument_id_id_key
                UNIQUE (instrument_id, id)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_instrument_versions
        ADD CONSTRAINT legal_instrument_versions_same_instrument_parent_fkey
        FOREIGN KEY (instrument_id, derived_from_version_id)
        REFERENCES corpus.legal_instrument_versions(instrument_id, id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        "CREATE INDEX legal_instrument_versions_timeline_idx "
        "ON corpus.legal_instrument_versions (instrument_id, valid_from, valid_to)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_instrument_version_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_version_id uuid NOT NULL,
            document_id uuid NOT NULL,
            document_role text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_version_documents_role_check CHECK (
                document_role IN (
                    'official_text', 'official_publication', 'consolidated_text',
                    'corrected_text', 'historical_copy', 'editorial_text', 'other'
                )
            ),
            CONSTRAINT legal_instrument_version_documents_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_instrument_version_documents_same_scope_version_fkey
                FOREIGN KEY (scope_id, instrument_version_id)
                REFERENCES corpus.legal_instrument_versions(scope_id, id),
            CONSTRAINT legal_instrument_version_documents_same_scope_document_fkey
                FOREIGN KEY (scope_id, document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_instrument_version_documents_unique
                UNIQUE (instrument_version_id, document_id, document_role)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_instrument_version_documents_document_idx "
        "ON corpus.legal_instrument_version_documents (scope_id, document_id)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_provisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_id uuid NOT NULL,
            identity_status text NOT NULL DEFAULT 'canonical',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_provisions_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate',
                    'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT legal_provisions_same_scope_instrument_fkey
                FOREIGN KEY (scope_id, instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_provisions_scope_id_id_key UNIQUE (scope_id, id),
            CONSTRAINT legal_provisions_instrument_id_id_key UNIQUE (instrument_id, id)
        )
        """
    )
    op.execute("CREATE INDEX legal_provisions_instrument_idx ON corpus.legal_provisions (instrument_id)")

    op.execute(
        f"""
        CREATE TABLE corpus.legal_provision_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_id uuid NOT NULL,
            instrument_version_id uuid NOT NULL,
            provision_id uuid NOT NULL,
            parent_provision_id uuid,
            provision_type text NOT NULL,
            label text,
            normalized_label text,
            ordinal integer,
            heading text,
            text text,
            content_status text NOT NULL DEFAULT 'candidate',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_provision_versions_type_check CHECK (
                provision_type IN (
                    'title', 'book', 'chapter', 'section', 'article', 'paragraph',
                    'clause', 'subclause', 'item', 'annex', 'preamble', 'other'
                )
            ),
            CONSTRAINT legal_provision_versions_ordinal_check
                CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT legal_provision_versions_status_check CHECK (
                content_status IN ('candidate', 'verified', 'conflicting', 'superseded')
            ),
            CONSTRAINT legal_provision_versions_not_self_parent_check
                CHECK (parent_provision_id IS NULL OR parent_provision_id <> provision_id),
            CONSTRAINT legal_provision_versions_same_instrument_version_fkey
                FOREIGN KEY (instrument_id, instrument_version_id)
                REFERENCES corpus.legal_instrument_versions(instrument_id, id),
            CONSTRAINT legal_provision_versions_same_instrument_provision_fkey
                FOREIGN KEY (instrument_id, provision_id)
                REFERENCES corpus.legal_provisions(instrument_id, id),
            CONSTRAINT legal_provision_versions_same_instrument_parent_fkey
                FOREIGN KEY (instrument_id, parent_provision_id)
                REFERENCES corpus.legal_provisions(instrument_id, id),
            CONSTRAINT legal_provision_versions_same_scope_provision_fkey
                FOREIGN KEY (scope_id, provision_id)
                REFERENCES corpus.legal_provisions(scope_id, id),
            CONSTRAINT legal_provision_versions_unique_version_provision
                UNIQUE (instrument_version_id, provision_id),
            CONSTRAINT legal_provision_versions_instrument_version_id_id_key
                UNIQUE (instrument_version_id, id)
        )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX legal_provision_versions_sibling_label_key
        ON corpus.legal_provision_versions (
            instrument_version_id,
            coalesce(parent_provision_id, '{ZERO_UUID}'::uuid),
            normalized_label
        )
        WHERE normalized_label IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX legal_provision_versions_provision_history_idx "
        "ON corpus.legal_provision_versions (provision_id, instrument_version_id)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_provision_version_sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_version_id uuid NOT NULL,
            provision_version_id uuid NOT NULL,
            source_document_id uuid NOT NULL,
            source_document_provision_id uuid,
            source_role text NOT NULL DEFAULT 'primary_text',
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_provision_version_sources_role_check CHECK (
                source_role IN (
                    'primary_text', 'official_consolidation', 'editorial_consolidation',
                    'correction', 'historical_copy', 'other'
                )
            ),
            CONSTRAINT legal_provision_version_sources_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_provision_version_sources_version_match_fkey
                FOREIGN KEY (instrument_version_id, provision_version_id)
                REFERENCES corpus.legal_provision_versions(instrument_version_id, id),
            CONSTRAINT legal_provision_version_sources_same_scope_version_fkey
                FOREIGN KEY (scope_id, instrument_version_id)
                REFERENCES corpus.legal_instrument_versions(scope_id, id),
            CONSTRAINT legal_provision_version_sources_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_provision_version_sources_document_provision_fkey
                FOREIGN KEY (source_document_id, source_document_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT legal_provision_version_sources_shape_check CHECK (
                source_document_provision_id IS NULL OR source_document_id IS NOT NULL
            ),
            CONSTRAINT legal_provision_version_sources_unique
                UNIQUE NULLS NOT DISTINCT (
                    provision_version_id, source_document_id,
                    source_document_provision_id, source_role
                )
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_instrument_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_id uuid NOT NULL,
            event_type text NOT NULL,
            occurred_on date,
            date_status text NOT NULL DEFAULT 'unknown',
            source_document_id uuid,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            raw_description text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_events_type_check CHECK (
                event_type IN (
                    'adopted', 'enacted', 'promulgated', 'published', 'effective',
                    'amended', 'corrected', 'suspended', 'reinstated',
                    'repealed', 'expired', 'other'
                )
            ),
            CONSTRAINT legal_instrument_events_date_status_check CHECK (
                date_status IN (
                    'verified_primary_text', 'verified_official_metadata',
                    'parsed_high_confidence', 'parsed_unverified', 'conflicting', 'unknown'
                )
            ),
            CONSTRAINT legal_instrument_events_verified_date_requires_date CHECK (
                date_status NOT IN (
                    'verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence'
                ) OR occurred_on IS NOT NULL
            ),
            CONSTRAINT legal_instrument_events_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_instrument_events_other_description_check CHECK (
                event_type <> 'other' OR btrim(coalesce(raw_description, '')) <> ''
            ),
            CONSTRAINT legal_instrument_events_same_scope_instrument_fkey
                FOREIGN KEY (scope_id, instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_instrument_events_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_instrument_events_timeline_idx "
        "ON corpus.legal_instrument_events (instrument_id, occurred_on, event_type)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_amendment_effects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            source_instrument_id uuid NOT NULL,
            source_version_id uuid,
            target_instrument_id uuid NOT NULL,
            target_provision_id uuid,
            effect_type text NOT NULL,
            effective_on date,
            raw_effect_text text,
            source_document_id uuid,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_amendment_effects_type_check CHECK (
                effect_type IN (
                    'amends', 'inserts', 'replaces', 'renumbers', 'repeals',
                    'partially_repeals', 'suspends', 'reinstates', 'corrects', 'other'
                )
            ),
            CONSTRAINT legal_amendment_effects_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_amendment_effects_other_text_check CHECK (
                effect_type <> 'other' OR btrim(coalesce(raw_effect_text, '')) <> ''
            ),
            CONSTRAINT legal_amendment_effects_same_scope_source_instrument_fkey
                FOREIGN KEY (scope_id, source_instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_amendment_effects_same_scope_target_instrument_fkey
                FOREIGN KEY (scope_id, target_instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_amendment_effects_source_version_fkey
                FOREIGN KEY (source_instrument_id, source_version_id)
                REFERENCES corpus.legal_instrument_versions(instrument_id, id),
            CONSTRAINT legal_amendment_effects_target_provision_fkey
                FOREIGN KEY (target_instrument_id, target_provision_id)
                REFERENCES corpus.legal_provisions(instrument_id, id),
            CONSTRAINT legal_amendment_effects_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_amendment_effects_target_idx "
        "ON corpus.legal_amendment_effects "
        "(target_instrument_id, target_provision_id, effective_on)"
    )
    op.execute(
        "CREATE INDEX legal_amendment_effects_source_idx "
        "ON corpus.legal_amendment_effects (source_instrument_id, effective_on)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.legal_instruments IS
        'Stable identity of a normative legal instrument. It is distinct from any one publication, consolidated text, or temporal version.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_instrument_versions IS
        'Temporal/legal text state of one stable legal instrument. Versions do not replace immutable source documents and may be candidate or derived until verified.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_provisions IS
        'Stable identity of a provision within an instrument. Labels, hierarchy, and text belong to provision versions because all may change over time.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_amendment_effects IS
        'Evidence-bearing legal effect caused by one instrument upon another instrument or provision. An amending law remains its own instrument rather than being collapsed into the target version.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.legal_amendment_effects")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_events")
    op.execute("DROP TABLE IF EXISTS corpus.legal_provision_version_sources")
    op.execute("DROP TABLE IF EXISTS corpus.legal_provision_versions")
    op.execute("DROP TABLE IF EXISTS corpus.legal_provisions")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_version_documents")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_versions")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_identifiers")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instruments")
