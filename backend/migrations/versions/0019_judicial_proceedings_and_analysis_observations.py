"""Add proceedings, procedural structure, and extensible analysis observations.

Revision ID: 0019_judicial_proceedings
Revises: 0018_multi_court_registry
Create Date: 2026-09-16

A judicial decision is not the same thing as the underlying proceeding. This
revision separates those identities, adds procedural participants/relations and
multi-clause dispositions, introduces normalized matter/procedure concepts while
preserving source-native text, and provides a quarantined JSONB observation
ledger for model discoveries that do not yet deserve canonical schema fields.
"""

from alembic import op

revision = "0019_judicial_proceedings"
down_revision = "0018_multi_court_registry"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.legal_matter_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            parent_id uuid REFERENCES corpus.legal_matter_concepts(id),
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_matter_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT legal_matter_concepts_name_nonempty CHECK (btrim(name) <> ''),
            CONSTRAINT legal_matter_concepts_not_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
            CONSTRAINT legal_matter_concepts_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_matter_concepts_parent_idx "
        "ON corpus.legal_matter_concepts (parent_id) WHERE parent_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.procedure_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            parent_id uuid REFERENCES corpus.procedure_concepts(id),
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedure_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT procedure_concepts_name_nonempty CHECK (btrim(name) <> ''),
            CONSTRAINT procedure_concepts_not_self_parent CHECK (parent_id IS NULL OR parent_id <> id),
            CONSTRAINT procedure_concepts_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX procedure_concepts_parent_idx "
        "ON corpus.procedure_concepts (parent_id) WHERE parent_id IS NOT NULL"
    )

    op.execute(
        """
        ALTER TABLE corpus.cases
            ADD COLUMN legal_matter_concept_id uuid
                REFERENCES corpus.legal_matter_concepts(id),
            ADD COLUMN procedure_concept_id uuid
                REFERENCES corpus.procedure_concepts(id)
        """
    )
    op.execute(
        "CREATE INDEX cases_legal_matter_concept_idx "
        "ON corpus.cases (legal_matter_concept_id) WHERE legal_matter_concept_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX cases_procedure_concept_idx "
        "ON corpus.cases (procedure_concept_id) WHERE procedure_concept_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_proceedings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            country_code character(2) NOT NULL DEFAULT 'DO',
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            originating_court_id uuid REFERENCES corpus.courts(id),
            legal_matter_concept_id uuid REFERENCES corpus.legal_matter_concepts(id),
            procedure_concept_id uuid REFERENCES corpus.procedure_concepts(id),
            canonical_title text,
            filing_date date,
            closed_date date,
            status text NOT NULL DEFAULT 'unknown',
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_proceedings_country_code_check CHECK (country_code ~ '^[A-Z]{{2}}$'),
            CONSTRAINT legal_proceedings_status_check CHECK (
                status IN ('unknown', 'pending', 'closed', 'stayed', 'archived')
            ),
            CONSTRAINT legal_proceedings_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate', 'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT legal_proceedings_date_range_check CHECK (
                closed_date IS NULL OR filing_date IS NULL OR closed_date >= filing_date
            ),
            CONSTRAINT legal_proceedings_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_proceedings_scope_status_idx "
        "ON corpus.legal_proceedings (scope_id, status, filing_date DESC)"
    )
    op.execute(
        "CREATE INDEX legal_proceedings_originating_court_idx "
        "ON corpus.legal_proceedings (originating_court_id, filing_date DESC) "
        "WHERE originating_court_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.proceeding_identifiers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            proceeding_id uuid NOT NULL REFERENCES corpus.legal_proceedings(id) ON DELETE CASCADE,
            identifier_type text NOT NULL,
            raw_value text NOT NULL,
            normalized_value text,
            court_id uuid REFERENCES corpus.courts(id),
            source_registry_id uuid REFERENCES corpus.source_registries(id),
            is_primary boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT proceeding_identifiers_type_check CHECK (
                identifier_type IN (
                    'expediente_number', 'docket_number', 'legacy_docket_number',
                    'source_specific_id', 'other'
                )
            ),
            CONSTRAINT proceeding_identifiers_raw_nonempty CHECK (btrim(raw_value) <> '')
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX proceeding_identifiers_identity_key
        ON corpus.proceeding_identifiers (
            proceeding_id, identifier_type, raw_value,
            coalesce(source_registry_id, '00000000-0000-0000-0000-000000000000'::uuid)
        )
        """
    )
    op.execute(
        "CREATE INDEX proceeding_identifiers_lookup_idx "
        "ON corpus.proceeding_identifiers (identifier_type, normalized_value) "
        "WHERE normalized_value IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.participants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            participant_kind text NOT NULL DEFAULT 'unknown',
            display_name text NOT NULL,
            normalized_name text,
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT participants_kind_check CHECK (
                participant_kind IN ('person', 'organization', 'public_body', 'unknown')
            ),
            CONSTRAINT participants_name_nonempty CHECK (btrim(display_name) <> ''),
            CONSTRAINT participants_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate', 'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT participants_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX participants_scope_normalized_name_idx "
        "ON corpus.participants (scope_id, normalized_name) "
        "WHERE normalized_name IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.proceeding_participants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proceeding_id uuid NOT NULL,
            participant_id uuid NOT NULL,
            participant_name_raw text NOT NULL,
            role_raw text NOT NULL,
            role_normalized text,
            party_side text NOT NULL DEFAULT 'other',
            ordinal integer,
            source_document_observation_id uuid
                REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT proceeding_participants_name_nonempty
                CHECK (btrim(participant_name_raw) <> ''),
            CONSTRAINT proceeding_participants_role_nonempty CHECK (btrim(role_raw) <> ''),
            CONSTRAINT proceeding_participants_side_check CHECK (
                party_side IN ('claimant', 'respondent', 'neutral', 'other')
            ),
            CONSTRAINT proceeding_participants_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT proceeding_participants_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')
            ),
            CONSTRAINT proceeding_participants_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT proceeding_participants_same_scope_participant_fkey
                FOREIGN KEY (scope_id, participant_id)
                REFERENCES corpus.participants(scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX proceeding_participants_proceeding_idx "
        "ON corpus.proceeding_participants (scope_id, proceeding_id, ordinal)"
    )
    op.execute(
        "CREATE INDEX proceeding_participants_participant_idx "
        "ON corpus.proceeding_participants (scope_id, participant_id)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.proceeding_decisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proceeding_id uuid NOT NULL,
            case_id uuid NOT NULL,
            relation_type text NOT NULL DEFAULT 'decision_in_proceeding',
            procedural_stage text,
            ordinal integer,
            is_primary boolean NOT NULL DEFAULT false,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT proceeding_decisions_relation_check CHECK (
                relation_type IN (
                    'decision_in_proceeding', 'reviews_proceeding',
                    'consolidates_proceeding', 'arises_from_proceeding'
                )
            ),
            CONSTRAINT proceeding_decisions_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT proceeding_decisions_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')
            ),
            CONSTRAINT proceeding_decisions_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT proceeding_decisions_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT proceeding_decisions_unique UNIQUE (proceeding_id, case_id, relation_type)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX proceeding_decisions_one_primary_per_case_idx "
        "ON corpus.proceeding_decisions (case_id) WHERE is_primary"
    )
    op.execute(
        "CREATE INDEX proceeding_decisions_proceeding_stage_idx "
        "ON corpus.proceeding_decisions (scope_id, proceeding_id, procedural_stage, ordinal)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.procedural_decision_relation_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            observation_key text NOT NULL,
            source_case_id uuid NOT NULL,
            relation_type text NOT NULL,
            target_case_id uuid,
            raw_target_reference text,
            assertion_method text NOT NULL,
            method_name text NOT NULL,
            confidence real,
            evidence_case_page_id uuid,
            evidence_excerpt text,
            status text NOT NULL DEFAULT 'observed',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedural_relation_observations_key_check
                CHECK (observation_key ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT procedural_relation_observations_type_check CHECK (
                relation_type IN (
                    'reviews', 'affirms', 'reverses', 'vacates', 'modifies', 'remands',
                    'cassates', 'partially_cassates', 'orders_new_trial', 'enforces', 'other'
                )
            ),
            CONSTRAINT procedural_relation_observations_target_check CHECK (
                target_case_id IS NOT NULL OR btrim(coalesce(raw_target_reference, '')) <> ''
            ),
            CONSTRAINT procedural_relation_observations_method_check CHECK (
                assertion_method IN (
                    'explicit_primary_text', 'official_metadata', 'deterministic_reference',
                    'llm_extracted', 'human_verified'
                )
            ),
            CONSTRAINT procedural_relation_observations_status_check CHECK (
                status IN ('observed', 'accepted', 'rejected', 'conflicting', 'superseded')
            ),
            CONSTRAINT procedural_relation_observations_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT procedural_relation_observations_same_scope_source_fkey
                FOREIGN KEY (scope_id, source_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT procedural_relation_observations_same_scope_target_fkey
                FOREIGN KEY (scope_id, target_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT procedural_relation_observations_same_case_evidence_fkey
                FOREIGN KEY (source_case_id, evidence_case_page_id)
                REFERENCES corpus.case_pages(case_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT procedural_relation_observations_identity_key UNIQUE (
                scope_id, observation_key
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX procedural_relation_observations_source_idx "
        "ON corpus.procedural_decision_relation_observations "
        "(scope_id, source_case_id, relation_type, status)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.procedural_decision_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            source_case_id uuid NOT NULL,
            relation_type text NOT NULL,
            target_case_id uuid NOT NULL,
            verification_method text NOT NULL,
            promoted_from_observation_id uuid
                REFERENCES corpus.procedural_decision_relation_observations(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedural_decision_relations_distinct_check
                CHECK (source_case_id <> target_case_id),
            CONSTRAINT procedural_decision_relations_type_check CHECK (
                relation_type IN (
                    'reviews', 'affirms', 'reverses', 'vacates', 'modifies', 'remands',
                    'cassates', 'partially_cassates', 'orders_new_trial', 'enforces', 'other'
                )
            ),
            CONSTRAINT procedural_decision_relations_same_scope_source_fkey
                FOREIGN KEY (scope_id, source_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT procedural_decision_relations_same_scope_target_fkey
                FOREIGN KEY (scope_id, target_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT procedural_decision_relations_unique UNIQUE (
                source_case_id, relation_type, target_case_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX procedural_decision_relations_source_idx "
        "ON corpus.procedural_decision_relations (scope_id, source_case_id, relation_type)"
    )
    op.execute(
        "CREATE INDEX procedural_decision_relations_target_idx "
        "ON corpus.procedural_decision_relations (scope_id, target_case_id, relation_type)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.case_dispositions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            case_id uuid NOT NULL,
            ordinal integer NOT NULL,
            disposition_type text NOT NULL,
            raw_text text NOT NULL,
            normalized_text text,
            affected_case_id uuid,
            affected_proceeding_id uuid,
            evidence_case_page_id uuid,
            extraction_method text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT case_dispositions_ordinal_check CHECK (ordinal > 0),
            CONSTRAINT case_dispositions_raw_text_nonempty CHECK (btrim(raw_text) <> ''),
            CONSTRAINT case_dispositions_type_check CHECK (
                disposition_type IN (
                    'granted', 'denied', 'dismissed', 'inadmissible', 'affirmed', 'reversed',
                    'vacated', 'modified', 'remanded', 'cassated', 'partially_cassated',
                    'costs', 'other'
                )
            ),
            CONSTRAINT case_dispositions_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')
            ),
            CONSTRAINT case_dispositions_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT case_dispositions_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT case_dispositions_same_scope_affected_case_fkey
                FOREIGN KEY (scope_id, affected_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT case_dispositions_same_scope_affected_proceeding_fkey
                FOREIGN KEY (scope_id, affected_proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT case_dispositions_same_case_evidence_fkey
                FOREIGN KEY (case_id, evidence_case_page_id)
                REFERENCES corpus.case_pages(case_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT case_dispositions_unique UNIQUE (case_id, ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX case_dispositions_case_type_idx "
        "ON corpus.case_dispositions (scope_id, case_id, disposition_type)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.analysis_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            observation_key text NOT NULL,
            subject_type text NOT NULL,
            case_id uuid,
            proceeding_id uuid,
            legal_document_id uuid,
            observation_type text NOT NULL,
            payload jsonb NOT NULL,
            evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
            producer_type text NOT NULL DEFAULT 'llm_agent',
            producer_name text NOT NULL,
            model_name text,
            model_version text,
            analysis_run_id text,
            schema_hint text,
            confidence real,
            status text NOT NULL DEFAULT 'observed',
            review_notes text,
            promoted_to_schema text,
            created_at timestamptz NOT NULL DEFAULT now(),
            reviewed_at timestamptz,
            CONSTRAINT analysis_observations_key_check
                CHECK (observation_key ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT analysis_observations_subject_type_check CHECK (
                subject_type IN ('case', 'proceeding', 'legal_document', 'corpus')
            ),
            CONSTRAINT analysis_observations_subject_shape_check CHECK (
                (subject_type = 'case' AND case_id IS NOT NULL
                    AND proceeding_id IS NULL AND legal_document_id IS NULL)
                OR
                (subject_type = 'proceeding' AND proceeding_id IS NOT NULL
                    AND case_id IS NULL AND legal_document_id IS NULL)
                OR
                (subject_type = 'legal_document' AND legal_document_id IS NOT NULL
                    AND case_id IS NULL AND proceeding_id IS NULL)
                OR
                (subject_type = 'corpus' AND case_id IS NULL
                    AND proceeding_id IS NULL AND legal_document_id IS NULL)
            ),
            CONSTRAINT analysis_observations_type_nonempty CHECK (btrim(observation_type) <> ''),
            CONSTRAINT analysis_observations_producer_name_nonempty CHECK (btrim(producer_name) <> ''),
            CONSTRAINT analysis_observations_payload_object_check
                CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT analysis_observations_evidence_array_check
                CHECK (jsonb_typeof(evidence) = 'array'),
            CONSTRAINT analysis_observations_producer_type_check CHECK (
                producer_type IN ('llm_agent', 'deterministic_tool', 'human', 'other')
            ),
            CONSTRAINT analysis_observations_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT analysis_observations_status_check CHECK (
                status IN ('observed', 'reviewed', 'promoted', 'rejected', 'superseded')
            ),
            CONSTRAINT analysis_observations_reviewed_at_check CHECK (
                reviewed_at IS NULL OR reviewed_at >= created_at
            ),
            CONSTRAINT analysis_observations_promoted_target_check CHECK (
                status <> 'promoted' OR btrim(coalesce(promoted_to_schema, '')) <> ''
            ),
            CONSTRAINT analysis_observations_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT analysis_observations_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT analysis_observations_same_scope_document_fkey
                FOREIGN KEY (scope_id, legal_document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT analysis_observations_identity_key UNIQUE (scope_id, observation_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX analysis_observations_review_queue_idx "
        "ON corpus.analysis_observations (scope_id, status, observation_type, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX analysis_observations_case_idx "
        "ON corpus.analysis_observations (scope_id, case_id, created_at DESC) "
        "WHERE case_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX analysis_observations_proceeding_idx "
        "ON corpus.analysis_observations (scope_id, proceeding_id, created_at DESC) "
        "WHERE proceeding_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX analysis_observations_payload_gin_idx "
        "ON corpus.analysis_observations USING gin (payload jsonb_path_ops)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.legal_proceedings IS
        'Underlying judicial proceeding or expediente. A proceeding may contain multiple judicial decisions and a decision may participate in multiple proceedings when consolidation or review requires it.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.procedural_decision_relations IS
        'Verified procedural history between decisions. It is intentionally separate from jurisprudential citation/treatment relations.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.matter IS
        'Source-facing/raw matter text retained even when legal_matter_concept_id is populated.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.procedure_type IS
        'Source-facing/raw procedure text retained even when procedure_concept_id is populated.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.analysis_observations IS
        'Quarantined extensibility ledger for analysis findings, especially LLM discoveries not yet modeled canonically. JSONB payloads never become source facts merely because they were submitted; promotion requires explicit review and a named canonical destination.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.analysis_observations")
    op.execute("DROP TABLE IF EXISTS corpus.case_dispositions")
    op.execute("DROP TABLE IF EXISTS corpus.procedural_decision_relations")
    op.execute("DROP TABLE IF EXISTS corpus.procedural_decision_relation_observations")
    op.execute("DROP TABLE IF EXISTS corpus.proceeding_decisions")
    op.execute("DROP TABLE IF EXISTS corpus.proceeding_participants")
    op.execute("DROP TABLE IF EXISTS corpus.participants")
    op.execute("DROP TABLE IF EXISTS corpus.proceeding_identifiers")
    op.execute("DROP TABLE IF EXISTS corpus.legal_proceedings")
    op.execute("DROP INDEX IF EXISTS corpus.cases_procedure_concept_idx")
    op.execute("DROP INDEX IF EXISTS corpus.cases_legal_matter_concept_idx")
    op.execute(
        """
        ALTER TABLE corpus.cases
            DROP COLUMN IF EXISTS procedure_concept_id,
            DROP COLUMN IF EXISTS legal_matter_concept_id
        """
    )
    op.execute("DROP TABLE IF EXISTS corpus.procedure_concepts")
    op.execute("DROP TABLE IF EXISTS corpus.legal_matter_concepts")
