"""Add legal reality foundations missing from the document-centric corpus model.

Revision ID: 0020_legal_reality
Revises: 0019_judicial_proceedings
Create Date: 2026-09-16

This migration adds identities that are distinct in real legal practice:
controversies that can span multiple proceedings, procedural events inside a
proceeding, judicial officers/panels, and evidence-bearing legal propositions.
It also fixes provision-label identity so repeated labels under different
articles/parents are legal instead of being rejected as duplicates.
"""

from alembic import op

revision = "0020_legal_reality"
down_revision = "0019_judicial_proceedings"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # A label such as "Párrafo I" is only unique among siblings. The previous
    # document-wide uniqueness rule rejected perfectly valid legal structures.
    op.execute("DROP INDEX IF EXISTS corpus.legal_document_provisions_label_key")
    op.execute(
        """
        CREATE UNIQUE INDEX legal_document_provisions_sibling_label_key
        ON corpus.legal_document_provisions (
            document_id,
            coalesce(parent_provision_id, '00000000-0000-0000-0000-000000000000'::uuid),
            normalized_label
        )
        WHERE normalized_label IS NOT NULL
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_controversies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            country_code character(2) NOT NULL DEFAULT 'DO',
            canonical_title text,
            status text NOT NULL DEFAULT 'unknown',
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            opened_on date,
            closed_on date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_controversies_country_code_check
                CHECK (country_code ~ '^[A-Z]{{2}}$'),
            CONSTRAINT legal_controversies_status_check CHECK (
                status IN ('unknown', 'active', 'closed', 'dormant', 'archived')
            ),
            CONSTRAINT legal_controversies_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate',
                    'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT legal_controversies_date_range_check CHECK (
                closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on
            ),
            CONSTRAINT legal_controversies_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_controversies_scope_status_idx "
        "ON corpus.legal_controversies (scope_id, status, opened_on DESC)"
    )

    op.execute("ALTER TABLE corpus.legal_proceedings ADD COLUMN controversy_id uuid")
    op.execute(
        """
        ALTER TABLE corpus.legal_proceedings
        ADD CONSTRAINT legal_proceedings_same_scope_controversy_fkey
        FOREIGN KEY (scope_id, controversy_id)
        REFERENCES corpus.legal_controversies(scope_id, id)
        DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        "CREATE INDEX legal_proceedings_controversy_idx "
        "ON corpus.legal_proceedings (scope_id, controversy_id, filing_date) "
        "WHERE controversy_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.procedural_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proceeding_id uuid NOT NULL,
            event_type text NOT NULL,
            event_type_raw text,
            occurred_on date,
            date_status text NOT NULL DEFAULT 'unknown',
            sequence_number integer,
            raw_description text,
            normalized_description text,
            source_document_observation_id uuid
                REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL,
            evidence_case_page_id uuid REFERENCES corpus.case_pages(id),
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedural_events_type_check CHECK (
                event_type IN (
                    'filing', 'service', 'hearing', 'motion', 'appeal', 'cassation_filing',
                    'constitutional_review_filing', 'evidence_submission', 'opinion_submission',
                    'interlocutory_order', 'decision_issued', 'remand', 'settlement',
                    'withdrawal', 'stay', 'execution', 'transfer', 'other'
                )
            ),
            CONSTRAINT procedural_events_date_status_check CHECK (
                date_status IN (
                    'verified_primary_text', 'verified_official_metadata',
                    'parsed_high_confidence', 'parsed_unverified', 'conflicting', 'unknown'
                )
            ),
            CONSTRAINT procedural_events_verified_date_requires_date CHECK (
                date_status NOT IN (
                    'verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence'
                ) OR occurred_on IS NOT NULL
            ),
            CONSTRAINT procedural_events_sequence_check
                CHECK (sequence_number IS NULL OR sequence_number > 0),
            CONSTRAINT procedural_events_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT procedural_events_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT procedural_events_description_check CHECK (
                event_type <> 'other'
                OR btrim(coalesce(event_type_raw, raw_description, '')) <> ''
            ),
            CONSTRAINT procedural_events_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX procedural_events_timeline_idx "
        "ON corpus.procedural_events "
        "(scope_id, proceeding_id, occurred_on, sequence_number, created_at)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.judicial_officers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            display_name text NOT NULL,
            normalized_name text,
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_officers_name_nonempty CHECK (btrim(display_name) <> ''),
            CONSTRAINT judicial_officers_identity_status_check CHECK (
                identity_status IN (
                    'canonical', 'probable_duplicate',
                    'identity_unresolved', 'merged_with_canonical'
                )
            ),
            CONSTRAINT judicial_officers_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_officers_name_idx "
        "ON corpus.judicial_officers (scope_id, normalized_name) "
        "WHERE normalized_name IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.decision_panel_members (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            case_id uuid NOT NULL,
            officer_id uuid NOT NULL,
            role_raw text NOT NULL,
            panel_role text NOT NULL DEFAULT 'member',
            ordinal integer,
            evidence_case_page_id uuid,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_panel_members_role_raw_nonempty CHECK (btrim(role_raw) <> ''),
            CONSTRAINT decision_panel_members_role_check CHECK (
                panel_role IN (
                    'presiding', 'rapporteur', 'ponente', 'member',
                    'dissenting', 'concurring', 'other'
                )
            ),
            CONSTRAINT decision_panel_members_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT decision_panel_members_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT decision_panel_members_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT decision_panel_members_same_scope_officer_fkey
                FOREIGN KEY (scope_id, officer_id)
                REFERENCES corpus.judicial_officers(scope_id, id),
            CONSTRAINT decision_panel_members_same_case_evidence_fkey
                FOREIGN KEY (case_id, evidence_case_page_id)
                REFERENCES corpus.case_pages(case_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT decision_panel_members_unique
                UNIQUE (case_id, officer_id, panel_role)
        )
        """
    )
    op.execute(
        "CREATE INDEX decision_panel_members_case_idx "
        "ON corpus.decision_panel_members (scope_id, case_id, ordinal)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_propositions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            proposition_type text NOT NULL,
            canonical_text text NOT NULL,
            normalized_text text,
            assertion_kind text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_propositions_type_check CHECK (
                proposition_type IN (
                    'issue', 'holding', 'legal_rule', 'legal_test', 'exception',
                    'material_fact', 'procedural_fact', 'argument', 'counterargument',
                    'reasoning', 'conclusion', 'dictum', 'other'
                )
            ),
            CONSTRAINT legal_propositions_text_nonempty CHECK (btrim(canonical_text) <> ''),
            CONSTRAINT legal_propositions_assertion_kind_check CHECK (
                assertion_kind IN (
                    'explicit_primary_text', 'derived_from_primary_text',
                    'synthesized_interpretation', 'human_authored'
                )
            ),
            CONSTRAINT legal_propositions_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_propositions_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT legal_propositions_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_propositions_type_status_idx "
        "ON corpus.legal_propositions (scope_id, proposition_type, verification_status)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_proposition_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proposition_id uuid NOT NULL,
            source_case_id uuid,
            source_document_id uuid,
            case_page_id uuid,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_role text NOT NULL DEFAULT 'supports',
            exact_excerpt text,
            char_start integer,
            char_end integer,
            extraction_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_proposition_evidence_source_check CHECK (
                source_case_id IS NOT NULL OR source_document_id IS NOT NULL
                OR artifact_page_id IS NOT NULL
            ),
            CONSTRAINT legal_proposition_evidence_role_check CHECK (
                evidence_role IN ('supports', 'qualifies', 'contradicts', 'context')
            ),
            CONSTRAINT legal_proposition_evidence_offsets_check CHECK (
                (char_start IS NULL AND char_end IS NULL)
                OR (
                    char_start IS NOT NULL AND char_end IS NOT NULL
                    AND char_start >= 0 AND char_end > char_start
                )
            ),
            CONSTRAINT legal_proposition_evidence_same_scope_proposition_fkey
                FOREIGN KEY (scope_id, proposition_id)
                REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_proposition_evidence_same_scope_case_fkey
                FOREIGN KEY (scope_id, source_case_id)
                REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT legal_proposition_evidence_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_proposition_evidence_same_case_page_fkey
                FOREIGN KEY (source_case_id, case_page_id)
                REFERENCES corpus.case_pages(case_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_proposition_evidence_proposition_idx "
        "ON corpus.legal_proposition_evidence (scope_id, proposition_id)"
    )
    op.execute(
        "CREATE INDEX legal_proposition_evidence_case_idx "
        "ON corpus.legal_proposition_evidence (scope_id, source_case_id) "
        "WHERE source_case_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_proposition_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            from_proposition_id uuid NOT NULL,
            relation_type text NOT NULL,
            to_proposition_id uuid NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            evidence_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_proposition_relations_distinct_check
                CHECK (from_proposition_id <> to_proposition_id),
            CONSTRAINT legal_proposition_relations_type_check CHECK (
                relation_type IN (
                    'answers', 'supports', 'opposes', 'qualifies', 'limits',
                    'creates_exception_to', 'depends_on', 'derived_from',
                    'applies_to', 'distinguishes_from'
                )
            ),
            CONSTRAINT legal_proposition_relations_status_check CHECK (
                verification_status IN (
                    'candidate', 'verified', 'conflicting', 'rejected', 'superseded'
                )
            ),
            CONSTRAINT legal_proposition_relations_from_scope_fkey
                FOREIGN KEY (scope_id, from_proposition_id)
                REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_proposition_relations_to_scope_fkey
                FOREIGN KEY (scope_id, to_proposition_id)
                REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_proposition_relations_unique
                UNIQUE (from_proposition_id, relation_type, to_proposition_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_proposition_relations_from_idx "
        "ON corpus.legal_proposition_relations (scope_id, from_proposition_id, relation_type)"
    )
    op.execute(
        "CREATE INDEX legal_proposition_relations_to_idx "
        "ON corpus.legal_proposition_relations (scope_id, to_proposition_id, relation_type)"
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.legal_controversies IS
        'A real-world dispute or litigation family that may span multiple court-specific proceedings/expedientes. It is not itself a judicial decision.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.procedural_events IS
        'Ordered/evidenced events inside a proceeding. A proceeding is not reducible to the set of judicial decisions issued in it.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_propositions IS
        'Evidence-bearing legal or factual propositions. assertion_kind preserves the boundary between explicit source text, derived structure, and interpretation.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.cases.id IS
        'Legacy physical table name: each row represents one judicial decision, not the full litigation controversy or proceeding.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.legal_proposition_relations")
    op.execute("DROP TABLE IF EXISTS corpus.legal_proposition_evidence")
    op.execute("DROP TABLE IF EXISTS corpus.legal_propositions")
    op.execute("DROP TABLE IF EXISTS corpus.decision_panel_members")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_officers")
    op.execute("DROP TABLE IF EXISTS corpus.procedural_events")
    op.execute("DROP INDEX IF EXISTS corpus.legal_proceedings_controversy_idx")
    op.execute(
        "ALTER TABLE corpus.legal_proceedings "
        "DROP CONSTRAINT IF EXISTS legal_proceedings_same_scope_controversy_fkey"
    )
    op.execute("ALTER TABLE corpus.legal_proceedings DROP COLUMN IF EXISTS controversy_id")
    op.execute("DROP TABLE IF EXISTS corpus.legal_controversies")
    op.execute("DROP INDEX IF EXISTS corpus.legal_document_provisions_sibling_label_key")
    op.execute(
        """
        CREATE UNIQUE INDEX legal_document_provisions_label_key
        ON corpus.legal_document_provisions (document_id, normalized_label)
        WHERE normalized_label IS NOT NULL
        """
    )
