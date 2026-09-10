"""Initial corpus schema.

Revision ID: 0001_initial_corpus_schema
Revises:
Create Date: 2026-09-10
"""

from alembic import op

revision = "0001_initial_corpus_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS corpus")

    op.execute(
        """
        CREATE TABLE corpus.source_registries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            institution text NOT NULL,
            authority_class text NOT NULL,
            base_locator text,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT source_registries_authority_class_check
                CHECK (authority_class IN ('official_primary', 'official_secondary', 'trusted_mirror', 'manual_import'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.source_artifacts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_registry_id uuid REFERENCES corpus.source_registries(id),
            sha256 text NOT NULL UNIQUE,
            mime_type text NOT NULL,
            byte_size bigint NOT NULL,
            page_count integer,
            acquired_at timestamptz NOT NULL DEFAULT now(),
            published_at date,
            parser_status text NOT NULL DEFAULT 'acquired',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT source_artifacts_sha256_check CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT source_artifacts_byte_size_check CHECK (byte_size >= 0),
            CONSTRAINT source_artifacts_page_count_check CHECK (page_count IS NULL OR page_count > 0),
            CONSTRAINT source_artifacts_parser_status_check
                CHECK (parser_status IN ('acquired', 'extracting', 'parsed', 'ocr_required', 'quality_review_required', 'searchable', 'blocked'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.source_artifact_locations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id uuid NOT NULL REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE,
            locator_type text NOT NULL,
            locator text NOT NULL,
            observed_filename text,
            is_preferred boolean NOT NULL DEFAULT false,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (locator_type, locator),
            CONSTRAINT source_artifact_locations_type_check
                CHECK (locator_type IN ('official_url', 'storage_object', 'mirror_url', 'manual_import'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.artifact_pages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_id uuid NOT NULL REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE,
            page_number integer NOT NULL,
            extracted_text text,
            text_sha256 text,
            extraction_method text,
            extraction_status text NOT NULL DEFAULT 'pending',
            ocr_confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (artifact_id, page_number),
            CONSTRAINT artifact_pages_number_check CHECK (page_number > 0),
            CONSTRAINT artifact_pages_text_sha256_check CHECK (text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT artifact_pages_status_check
                CHECK (extraction_status IN ('pending', 'native_text', 'ocr_complete', 'quality_review_required', 'blocked')),
            CONSTRAINT artifact_pages_ocr_confidence_check
                CHECK (ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.courts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            short_name text,
            jurisdiction text NOT NULL,
            country_code char(2) NOT NULL DEFAULT 'DO',
            authority_rank smallint,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT courts_active_range_check CHECK (active_to IS NULL OR active_from IS NULL OR active_to >= active_from)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.court_organs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id),
            code text NOT NULL,
            name text NOT NULL,
            organ_type text NOT NULL,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (court_id, code),
            CONSTRAINT court_organs_active_range_check CHECK (active_to IS NULL OR active_from IS NULL OR active_to >= active_from)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.cases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id),
            court_organ_id uuid REFERENCES corpus.court_organs(id),
            decision_number text,
            normalized_decision_number text,
            decision_date date,
            decision_date_status text NOT NULL DEFAULT 'unknown',
            decision_date_evidence_page_id uuid REFERENCES corpus.artifact_pages(id),
            title text,
            matter text,
            procedure_type text,
            language text NOT NULL DEFAULT 'es',
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            quality_status text NOT NULL DEFAULT 'unreviewed',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT cases_decision_date_status_check
                CHECK (decision_date_status IN ('verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence', 'parsed_unverified', 'conflicting', 'unknown')),
            CONSTRAINT cases_identity_status_check
                CHECK (identity_status IN ('canonical', 'probable_duplicate', 'identity_unresolved', 'merged_with_canonical')),
            CONSTRAINT cases_quality_status_check
                CHECK (quality_status IN ('unreviewed', 'searchable', 'quality_review_required', 'blocked')),
            CONSTRAINT cases_verified_date_requires_date_check
                CHECK (decision_date_status NOT IN ('verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence') OR decision_date IS NOT NULL)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.case_identifiers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            identifier_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_value text,
            is_primary boolean NOT NULL DEFAULT false,
            evidence_page_id uuid REFERENCES corpus.artifact_pages(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT case_identifiers_type_check
                CHECK (identifier_type IN ('decision_number', 'docket_number', 'legacy_docket_number', 'source_specific_id', 'other'))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.case_artifact_occurrences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            artifact_id uuid NOT NULL REFERENCES corpus.source_artifacts(id) ON DELETE CASCADE,
            start_page integer NOT NULL,
            end_page integer NOT NULL,
            segmentation_status text NOT NULL DEFAULT 'candidate',
            segmentation_method text NOT NULL,
            segmentation_confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (case_id, artifact_id, start_page, end_page),
            CONSTRAINT case_artifact_occurrences_page_range_check CHECK (start_page > 0 AND end_page >= start_page),
            CONSTRAINT case_artifact_occurrences_status_check
                CHECK (segmentation_status IN ('candidate', 'verified', 'ambiguous', 'rejected')),
            CONSTRAINT case_artifact_occurrences_confidence_check
                CHECK (segmentation_confidence IS NULL OR (segmentation_confidence >= 0 AND segmentation_confidence <= 1))
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.case_pages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            artifact_page_id uuid NOT NULL REFERENCES corpus.artifact_pages(id),
            ordinal_in_case integer NOT NULL,
            printed_page_label text,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (case_id, ordinal_in_case),
            UNIQUE (case_id, artifact_page_id),
            CONSTRAINT case_pages_ordinal_check CHECK (ordinal_in_case > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.passages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            page_start integer NOT NULL,
            page_end integer NOT NULL,
            passage_order integer NOT NULL,
            text text NOT NULL,
            section_type text,
            token_count integer,
            fts tsvector GENERATED ALWAYS AS (to_tsvector('spanish', coalesce(text, ''))) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (case_id, passage_order),
            CONSTRAINT passages_page_range_check CHECK (page_start > 0 AND page_end >= page_start),
            CONSTRAINT passages_token_count_check CHECK (token_count IS NULL OR token_count >= 0)
        )
        """
    )

    op.execute("CREATE INDEX source_artifact_locations_artifact_idx ON corpus.source_artifact_locations (artifact_id)")
    op.execute("CREATE INDEX artifact_pages_artifact_page_idx ON corpus.artifact_pages (artifact_id, page_number)")
    op.execute("CREATE INDEX court_organs_court_idx ON corpus.court_organs (court_id)")
    op.execute("CREATE INDEX cases_decision_date_idx ON corpus.cases (decision_date DESC) WHERE decision_date IS NOT NULL")
    op.execute("CREATE INDEX cases_court_date_idx ON corpus.cases (court_id, decision_date DESC) WHERE decision_date IS NOT NULL")
    op.execute("CREATE INDEX cases_organ_date_idx ON corpus.cases (court_organ_id, decision_date DESC) WHERE court_organ_id IS NOT NULL AND decision_date IS NOT NULL")
    op.execute("CREATE INDEX cases_normalized_decision_number_idx ON corpus.cases (normalized_decision_number) WHERE normalized_decision_number IS NOT NULL")
    op.execute("CREATE INDEX case_identifiers_lookup_idx ON corpus.case_identifiers (identifier_type, normalized_value) WHERE normalized_value IS NOT NULL")
    op.execute("CREATE INDEX case_artifact_occurrences_artifact_idx ON corpus.case_artifact_occurrences (artifact_id, start_page, end_page)")
    op.execute("CREATE INDEX case_pages_artifact_page_idx ON corpus.case_pages (artifact_page_id)")
    op.execute("CREATE INDEX passages_case_page_idx ON corpus.passages (case_id, page_start, page_end)")
    op.execute("CREATE INDEX passages_fts_idx ON corpus.passages USING gin (fts)")

    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.decision_date IS
        'Date on which the judicial decision itself was rendered. Not publication, acquisition, filing, or lower-court date.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.decision_date_status IS
        'Verification/provenance state for decision_date; temporal legal research must not silently treat unknown/conflicting dates as verified.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.source_artifact_locations IS
        'Preserves every observed URL/storage locator even when multiple locators resolve to identical artifact bytes.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.case_artifact_occurrences IS
        'Maps one canonical judicial case to the exact page range where it occurs inside a source artifact or compilation.'
        """
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS corpus CASCADE")
