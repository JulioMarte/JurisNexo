"""Add proceeding-level judicial intelligence schema.

Revision ID: 0017_judicial_proceedings
Revises: 0016_source_obs_idempotency
Create Date: 2026-09-14

Judicial decisions are not the same thing as the underlying expediente or
proceeding. This migration adds a source-neutral proceeding layer, typed
participants, procedural decision relations, structured dispositions, judicial
officers, normalized matter/procedure vocabularies, court hierarchy metadata,
and explicit source-record-to-canonical-document resolution.
"""

from alembic import op

revision = "0017_judicial_proceedings"
down_revision = "0016_source_obs_idempotency"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.courts
        ADD COLUMN parent_court_id uuid REFERENCES corpus.courts(id),
        ADD COLUMN court_level text,
        ADD COLUMN territorial_jurisdiction text,
        ADD CONSTRAINT courts_not_self_parent_check
            CHECK (parent_court_id IS NULL OR parent_court_id <> id)
        """
    )
    op.execute(
        "CREATE INDEX courts_parent_idx ON corpus.courts (parent_court_id) "
        "WHERE parent_court_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX courts_level_idx ON corpus.courts (court_level) "
        "WHERE court_level IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_matters (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            parent_id uuid REFERENCES corpus.legal_matters(id),
            jurisdiction_code text,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_matters_code_check CHECK (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            CONSTRAINT legal_matters_name_nonempty CHECK (btrim(name) <> ''),
            CONSTRAINT legal_matters_not_self_parent_check CHECK (parent_id IS NULL OR parent_id <> id),
            CONSTRAINT legal_matters_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_matters_parent_idx ON corpus.legal_matters (parent_id) "
        "WHERE parent_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.procedure_types (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            parent_id uuid REFERENCES corpus.procedure_types(id),
            jurisdiction_code text,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedure_types_code_check CHECK (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            CONSTRAINT procedure_types_name_nonempty CHECK (btrim(name) <> ''),
            CONSTRAINT procedure_types_not_self_parent_check CHECK (parent_id IS NULL OR parent_id <> id),
            CONSTRAINT procedure_types_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX procedure_types_parent_idx ON corpus.procedure_types (parent_id) "
        "WHERE parent_id IS NOT NULL"
    )

    op.execute(
        """
        ALTER TABLE corpus.cases
        ADD COLUMN legal_matter_id uuid REFERENCES corpus.legal_matters(id),
        ADD COLUMN procedure_type_id uuid REFERENCES corpus.procedure_types(id)
        """
    )
    op.execute(
        "CREATE INDEX cases_legal_matter_idx ON corpus.cases (legal_matter_id) "
        "WHERE legal_matter_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX cases_procedure_type_idx ON corpus.cases (procedure_type_id) "
        "WHERE procedure_type_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.judicial_proceedings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            jurisdiction_code text NOT NULL DEFAULT 'DO',
            originating_court_id uuid REFERENCES corpus.courts(id),
            primary_matter_id uuid REFERENCES corpus.legal_matters(id),
            procedure_type_id uuid REFERENCES corpus.procedure_types(id),
            title text,
            filing_date date,
            closed_date date,
            status text NOT NULL DEFAULT 'unknown',
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_proceedings_status_check CHECK (
                status IN ('unknown', 'open', 'closed', 'stayed', 'archived')
            ),
            CONSTRAINT judicial_proceedings_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate', 'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT judicial_proceedings_date_range_check CHECK (
                closed_date IS NULL OR filing_date IS NULL OR closed_date >= filing_date
            ),
            CONSTRAINT judicial_proceedings_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_proceedings_court_idx "
        "ON corpus.judicial_proceedings (originating_court_id) "
        "WHERE originating_court_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX judicial_proceedings_matter_idx "
        "ON corpus.judicial_proceedings (primary_matter_id) "
        "WHERE primary_matter_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.judicial_proceeding_identifiers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            proceeding_id uuid NOT NULL REFERENCES corpus.judicial_proceedings(id) ON DELETE CASCADE,
            court_id uuid REFERENCES corpus.courts(id),
            source_registry_id uuid REFERENCES corpus.source_registries(id),
            identifier_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_value text,
            is_primary boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_proceeding_identifiers_type_check CHECK (
                identifier_type IN (
                    'expediente_number', 'docket_number', 'legacy_docket_number',
                    'source_specific_id', 'other'
                )
            ),
            CONSTRAINT judicial_proceeding_identifiers_raw_nonempty CHECK (btrim(raw_value) <> ''),
            CONSTRAINT judicial_proceeding_identifiers_unique UNIQUE (
                proceeding_id, identifier_type, raw_value, source_registry_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_proceeding_identifiers_lookup_idx "
        "ON corpus.judicial_proceeding_identifiers (identifier_type, normalized_value) "
        "WHERE normalized_value IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.judicial_proceeding_participants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            proceeding_id uuid NOT NULL REFERENCES corpus.judicial_proceedings(id) ON DELETE CASCADE,
            participant_name_raw text NOT NULL,
            participant_name_normalized text,
            participant_kind text NOT NULL DEFAULT 'unknown',
            role_raw text,
            role_normalized text,
            party_side text,
            participant_order integer,
            source_document_observation_id uuid
                REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL,
            evidence_case_page_id uuid REFERENCES corpus.case_pages(id) ON DELETE SET NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_proceeding_participants_name_nonempty CHECK (
                btrim(participant_name_raw) <> ''
            ),
            CONSTRAINT judicial_proceeding_participants_kind_check CHECK (
                participant_kind IN ('person', 'organization', 'public_body', 'unknown')
            ),
            CONSTRAINT judicial_proceeding_participants_side_check CHECK (
                party_side IS NULL OR party_side IN ('claimant', 'respondent', 'neutral', 'other')
            ),
            CONSTRAINT judicial_proceeding_participants_order_check CHECK (
                participant_order IS NULL OR participant_order > 0
            ),
            CONSTRAINT judicial_proceeding_participants_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'ambiguous', 'rejected')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_proceeding_participants_proceeding_idx "
        "ON corpus.judicial_proceeding_participants (proceeding_id, role_normalized)"
    )
    op.execute(
        "CREATE INDEX judicial_proceeding_participants_name_idx "
        "ON corpus.judicial_proceeding_participants (participant_name_normalized) "
        "WHERE participant_name_normalized IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.case_proceedings (
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            proceeding_id uuid NOT NULL REFERENCES corpus.judicial_proceedings(id) ON DELETE CASCADE,
            relation_type text NOT NULL DEFAULT 'decision_in_proceeding',
            is_primary boolean NOT NULL DEFAULT false,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (case_id, proceeding_id, relation_type),
            CONSTRAINT case_proceedings_relation_type_check CHECK (
                relation_type IN (
                    'decision_in_proceeding', 'reviews_proceeding',
                    'consolidates_proceeding', 'arises_from_proceeding'
                )
            ),
            CONSTRAINT case_proceedings_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'ambiguous', 'rejected')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX case_proceedings_proceeding_idx "
        "ON corpus.case_proceedings (proceeding_id, relation_type)"
    )
    op.execute(
        "CREATE UNIQUE INDEX case_proceedings_primary_case_idx "
        "ON corpus.case_proceedings (case_id) WHERE is_primary"
    )

    op.execute(
        """
        CREATE TABLE corpus.judicial_decision_relation_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            observation_key text NOT NULL UNIQUE,
            source_case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            relation_type text NOT NULL,
            target_case_id uuid REFERENCES corpus.cases(id) ON DELETE CASCADE,
            raw_target_reference text,
            assertion_method text NOT NULL,
            method_name text NOT NULL,
            confidence real,
            evidence_case_page_id uuid REFERENCES corpus.case_pages(id) ON DELETE SET NULL,
            evidence_excerpt text,
            status text NOT NULL DEFAULT 'observed',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_decision_relation_observations_key_check CHECK (
                observation_key ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT judicial_decision_relation_observations_type_check CHECK (
                relation_type IN (
                    'reviews', 'affirms', 'reverses', 'vacates', 'modifies',
                    'remands', 'cassates', 'partially_cassates',
                    'orders_new_trial', 'enforces', 'other'
                )
            ),
            CONSTRAINT judicial_decision_relation_observations_method_check CHECK (
                assertion_method IN (
                    'explicit_primary_text', 'official_metadata',
                    'deterministic_reference', 'llm_extracted', 'human_verified'
                )
            ),
            CONSTRAINT judicial_decision_relation_observations_status_check CHECK (
                status IN ('observed', 'accepted', 'rejected', 'conflicting', 'superseded')
            ),
            CONSTRAINT judicial_decision_relation_observations_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT judicial_decision_relation_observations_target_check CHECK (
                target_case_id IS NOT NULL OR btrim(coalesce(raw_target_reference, '')) <> ''
            ),
            CONSTRAINT judicial_decision_relation_observations_not_self_check CHECK (
                target_case_id IS NULL OR target_case_id <> source_case_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_decision_relation_observations_source_idx "
        "ON corpus.judicial_decision_relation_observations "
        "(source_case_id, relation_type, status)"
    )

    op.execute(
        """
        CREATE TABLE corpus.judicial_decision_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            relation_type text NOT NULL,
            target_case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'verified',
            verification_method text NOT NULL,
            promoted_from_observation_id uuid
                REFERENCES corpus.judicial_decision_relation_observations(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_decision_relations_type_check CHECK (
                relation_type IN (
                    'reviews', 'affirms', 'reverses', 'vacates', 'modifies',
                    'remands', 'cassates', 'partially_cassates',
                    'orders_new_trial', 'enforces', 'other'
                )
            ),
            CONSTRAINT judicial_decision_relations_status_check CHECK (
                status IN ('verified', 'conflicting', 'superseded')
            ),
            CONSTRAINT judicial_decision_relations_not_self_check CHECK (
                target_case_id <> source_case_id
            ),
            CONSTRAINT judicial_decision_relations_identity_key UNIQUE (
                source_case_id, relation_type, target_case_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_decision_relations_target_idx "
        "ON corpus.judicial_decision_relations (target_case_id, relation_type, status)"
    )

    op.execute(
        """
        CREATE TABLE corpus.case_dispositions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            ordinal integer NOT NULL,
            disposition_type text NOT NULL,
            raw_text text NOT NULL,
            affected_case_id uuid REFERENCES corpus.cases(id) ON DELETE SET NULL,
            affected_proceeding_id uuid REFERENCES corpus.judicial_proceedings(id) ON DELETE SET NULL,
            evidence_case_page_id uuid REFERENCES corpus.case_pages(id) ON DELETE SET NULL,
            extraction_method text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT case_dispositions_ordinal_check CHECK (ordinal > 0),
            CONSTRAINT case_dispositions_type_check CHECK (
                disposition_type IN (
                    'granted', 'denied', 'dismissed', 'inadmissible',
                    'affirmed', 'reversed', 'vacated', 'modified', 'remanded',
                    'cassated', 'partially_cassated', 'costs', 'other'
                )
            ),
            CONSTRAINT case_dispositions_raw_nonempty CHECK (btrim(raw_text) <> ''),
            CONSTRAINT case_dispositions_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'ambiguous', 'rejected')
            ),
            CONSTRAINT case_dispositions_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT case_dispositions_case_ordinal_key UNIQUE (case_id, ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX case_dispositions_type_idx "
        "ON corpus.case_dispositions (disposition_type, verification_status)"
    )

    op.execute(
        """
        CREATE TABLE corpus.judicial_officers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            country_code character(2) NOT NULL DEFAULT 'DO',
            display_name text NOT NULL,
            normalized_name text,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_officers_country_code_check CHECK (country_code ~ '^[A-Z]{2}$'),
            CONSTRAINT judicial_officers_name_nonempty CHECK (btrim(display_name) <> ''),
            CONSTRAINT judicial_officers_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_officers_name_idx "
        "ON corpus.judicial_officers (normalized_name) WHERE normalized_name IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.case_judicial_officers (
            case_id uuid NOT NULL REFERENCES corpus.cases(id) ON DELETE CASCADE,
            judicial_officer_id uuid NOT NULL REFERENCES corpus.judicial_officers(id),
            role text NOT NULL,
            ordinal integer,
            source_document_observation_id uuid
                REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL,
            evidence_case_page_id uuid REFERENCES corpus.case_pages(id) ON DELETE SET NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (case_id, judicial_officer_id, role),
            CONSTRAINT case_judicial_officers_role_check CHECK (
                role IN (
                    'presiding_judge', 'rapporteur', 'judge',
                    'dissenting_judge', 'concurring_judge'
                )
            ),
            CONSTRAINT case_judicial_officers_ordinal_check CHECK (
                ordinal IS NULL OR ordinal > 0
            ),
            CONSTRAINT case_judicial_officers_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'ambiguous', 'rejected')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX case_judicial_officers_officer_idx "
        "ON corpus.case_judicial_officers (judicial_officer_id, role)"
    )

    op.execute(
        """
        CREATE TABLE corpus.source_document_canonical_resolutions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id uuid NOT NULL
                REFERENCES corpus.source_documents(id) ON DELETE CASCADE,
            legal_document_id uuid NOT NULL
                REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            resolution_status text NOT NULL DEFAULT 'candidate',
            resolution_method text NOT NULL,
            confidence real,
            matched_on jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT source_document_canonical_resolutions_status_check CHECK (
                resolution_status IN ('candidate', 'verified', 'ambiguous', 'rejected')
            ),
            CONSTRAINT source_document_canonical_resolutions_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT source_document_canonical_resolutions_identity_key UNIQUE (
                source_document_id, legal_document_id
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX source_document_one_verified_canonical_idx "
        "ON corpus.source_document_canonical_resolutions (source_document_id) "
        "WHERE resolution_status = 'verified'"
    )
    op.execute(
        "CREATE INDEX source_document_canonical_legal_document_idx "
        "ON corpus.source_document_canonical_resolutions (legal_document_id, resolution_status)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.judicial_proceedings IS
        'Canonical expediente/proceeding identity. A proceeding may yield multiple decisions across multiple courts and may contain multiple source-native identifiers.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.judicial_proceeding_participants IS
        'Source-traceable participants in a judicial proceeding. Raw names and roles are preserved separately from normalized analytical values.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.judicial_decision_relation_observations IS
        'Evidence-bearing candidate procedural relationships between judicial decisions. Model output remains observational until separately promoted.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.case_dispositions IS
        'Structured decision outcomes/dispositive clauses with retained raw source text and verification state.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.source_document_canonical_resolutions IS
        'Resolves source-native published records such as Principales, standalone SCJ decisions, or historical records onto one canonical legal document without conflating source identity with legal identity.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.source_document_canonical_resolutions")
    op.execute("DROP TABLE IF EXISTS corpus.case_judicial_officers")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_officers")
    op.execute("DROP TABLE IF EXISTS corpus.case_dispositions")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_decision_relations")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_decision_relation_observations")
    op.execute("DROP TABLE IF EXISTS corpus.case_proceedings")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_proceeding_participants")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_proceeding_identifiers")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_proceedings")
    op.execute("DROP INDEX IF EXISTS corpus.cases_procedure_type_idx")
    op.execute("DROP INDEX IF EXISTS corpus.cases_legal_matter_idx")
    op.execute(
        "ALTER TABLE corpus.cases DROP COLUMN IF EXISTS procedure_type_id, "
        "DROP COLUMN IF EXISTS legal_matter_id"
    )
    op.execute("DROP TABLE IF EXISTS corpus.procedure_types")
    op.execute("DROP TABLE IF EXISTS corpus.legal_matters")
    op.execute("DROP INDEX IF EXISTS corpus.courts_level_idx")
    op.execute("DROP INDEX IF EXISTS corpus.courts_parent_idx")
    op.execute(
        "ALTER TABLE corpus.courts "
        "DROP CONSTRAINT IF EXISTS courts_not_self_parent_check, "
        "DROP COLUMN IF EXISTS territorial_jurisdiction, "
        "DROP COLUMN IF EXISTS court_level, "
        "DROP COLUMN IF EXISTS parent_court_id"
    )
