"""Model comprehensive legal semantics and bitemporal knowledge.

Revision ID: 0024_comprehensive_semantics
Revises: 0023_harden_legal_temporal
Create Date: 2026-09-16

The database is intentionally empty at this stage, so this revision favors a
clean future model over compatibility with weak early abstractions.  It adds
true valid-time/system-time knowledge history, normalized institutional and
party roles, judicial career/opinion/vote identities, DAG classifications,
legal-status events, contextual precedential authority/treatments, provision
lineage, and reconstructable amendment operations.
"""

from alembic import op

revision = "0024_comprehensive_semantics"
down_revision = "0023_harden_legal_temporal"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # Stable provision-version identities need a scope-qualified key so all new
    # evidence/knowledge tables can enforce tenant boundaries in PostgreSQL.
    op.execute(
        "ALTER TABLE corpus.legal_provision_versions "
        "ADD CONSTRAINT legal_provision_versions_scope_id_id_key UNIQUE (scope_id, id)"
    )

    # A matter/procedure can have several broader concepts.  The old parent_id
    # encoded a tree and therefore could not represent a legal taxonomy DAG.
    op.execute("DROP INDEX IF EXISTS corpus.legal_matter_concepts_parent_idx")
    op.execute("ALTER TABLE corpus.legal_matter_concepts DROP COLUMN parent_id")
    op.execute("DROP INDEX IF EXISTS corpus.procedure_concepts_parent_idx")
    op.execute("ALTER TABLE corpus.procedure_concepts DROP COLUMN parent_id")

    op.execute(
        """
        CREATE TABLE corpus.legal_matter_concept_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            narrower_concept_id uuid NOT NULL
                REFERENCES corpus.legal_matter_concepts(id) ON DELETE CASCADE,
            broader_concept_id uuid NOT NULL
                REFERENCES corpus.legal_matter_concepts(id) ON DELETE CASCADE,
            relation_type text NOT NULL DEFAULT 'broader',
            verification_status text NOT NULL DEFAULT 'verified',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_matter_concept_edges_distinct_check
                CHECK (narrower_concept_id <> broader_concept_id),
            CONSTRAINT legal_matter_concept_edges_relation_check
                CHECK (relation_type IN ('broader', 'part_of', 'related')),
            CONSTRAINT legal_matter_concept_edges_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_matter_concept_edges_unique
                UNIQUE (narrower_concept_id, broader_concept_id, relation_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_matter_concept_edges_broader_idx "
        "ON corpus.legal_matter_concept_edges (broader_concept_id, relation_type)"
    )

    op.execute(
        """
        CREATE TABLE corpus.procedure_concept_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            narrower_concept_id uuid NOT NULL
                REFERENCES corpus.procedure_concepts(id) ON DELETE CASCADE,
            broader_concept_id uuid NOT NULL
                REFERENCES corpus.procedure_concepts(id) ON DELETE CASCADE,
            relation_type text NOT NULL DEFAULT 'broader',
            verification_status text NOT NULL DEFAULT 'verified',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedure_concept_edges_distinct_check
                CHECK (narrower_concept_id <> broader_concept_id),
            CONSTRAINT procedure_concept_edges_relation_check
                CHECK (relation_type IN ('broader', 'part_of', 'related')),
            CONSTRAINT procedure_concept_edges_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT procedure_concept_edges_unique
                UNIQUE (narrower_concept_id, broader_concept_id, relation_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX procedure_concept_edges_broader_idx "
        "ON corpus.procedure_concept_edges (broader_concept_id, relation_type)"
    )

    # Bitemporal knowledge: legal validity and JurisNexo knowledge time are
    # independent.  Corrections append records; they never rewrite history.
    op.execute(
        f"""
        CREATE TABLE corpus.legal_instrument_version_knowledge (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_version_id uuid NOT NULL,
            valid_from date,
            valid_to date,
            known_from timestamptz NOT NULL,
            known_to timestamptz,
            asserted_status text NOT NULL DEFAULT 'candidate',
            assertion_method text NOT NULL,
            source_document_id uuid,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_version_knowledge_valid_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_instrument_version_knowledge_known_range_check
                CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT legal_instrument_version_knowledge_status_check
                CHECK (asserted_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_instrument_version_knowledge_same_scope_version_fkey
                FOREIGN KEY (scope_id, instrument_version_id)
                REFERENCES corpus.legal_instrument_versions(scope_id, id),
            CONSTRAINT legal_instrument_version_knowledge_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_instrument_version_knowledge_unique
                UNIQUE (instrument_version_id, known_from)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_instrument_version_knowledge_asof_idx "
        "ON corpus.legal_instrument_version_knowledge "
        "(instrument_version_id, valid_from, valid_to, known_from, known_to)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_provision_version_knowledge (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            provision_version_id uuid NOT NULL,
            valid_from date,
            valid_to date,
            known_from timestamptz NOT NULL,
            known_to timestamptz,
            heading text,
            text text,
            content_status text NOT NULL DEFAULT 'candidate',
            assertion_method text NOT NULL,
            source_document_id uuid,
            source_document_provision_id uuid,
            exact_excerpt text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_provision_version_knowledge_valid_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_provision_version_knowledge_known_range_check
                CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT legal_provision_version_knowledge_status_check
                CHECK (content_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_provision_version_knowledge_same_scope_version_fkey
                FOREIGN KEY (scope_id, provision_version_id)
                REFERENCES corpus.legal_provision_versions(scope_id, id),
            CONSTRAINT legal_provision_version_knowledge_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id)
                REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_provision_version_knowledge_document_provision_fkey
                FOREIGN KEY (source_document_id, source_document_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id),
            CONSTRAINT legal_provision_version_knowledge_source_shape_check
                CHECK (source_document_provision_id IS NULL OR source_document_id IS NOT NULL),
            CONSTRAINT legal_provision_version_knowledge_unique
                UNIQUE (provision_version_id, known_from)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_provision_version_knowledge_asof_idx "
        "ON corpus.legal_provision_version_knowledge "
        "(provision_version_id, valid_from, valid_to, known_from, known_to)"
    )

    # Normalized public institutions / issuing authorities. Raw source wording
    # remains on source observations; canonical authority identity lives here.
    op.execute(
        f"""
        CREATE TABLE corpus.legal_authorities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            authority_type text NOT NULL,
            canonical_name text NOT NULL,
            normalized_name text,
            country_code character(2) NOT NULL DEFAULT 'DO',
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_authorities_type_check CHECK (
                authority_type IN (
                    'legislature', 'executive', 'ministry', 'regulator', 'municipality',
                    'court', 'constitutional_body', 'international_body', 'other'
                )
            ),
            CONSTRAINT legal_authorities_name_nonempty CHECK (btrim(canonical_name) <> ''),
            CONSTRAINT legal_authorities_country_check CHECK (country_code ~ '^[A-Z]{{2}}$'),
            CONSTRAINT legal_authorities_identity_status_check CHECK (
                identity_status IN ('canonical', 'probable_duplicate', 'identity_unresolved', 'merged_with_canonical')
            ),
            CONSTRAINT legal_authorities_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_authorities_name_idx ON corpus.legal_authorities "
        "(scope_id, normalized_name) WHERE normalized_name IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_instrument_authority_roles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            instrument_id uuid NOT NULL,
            authority_id uuid NOT NULL,
            authority_role text NOT NULL,
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_instrument_authority_roles_role_check CHECK (
                authority_role IN (
                    'enacted_by', 'promulgated_by', 'issued_by', 'published_by',
                    'administered_by', 'enforced_by', 'delegated_by', 'other'
                )
            ),
            CONSTRAINT legal_instrument_authority_roles_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_instrument_authority_roles_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_instrument_authority_roles_same_scope_instrument_fkey
                FOREIGN KEY (scope_id, instrument_id)
                REFERENCES corpus.legal_instruments(scope_id, id),
            CONSTRAINT legal_instrument_authority_roles_same_scope_authority_fkey
                FOREIGN KEY (scope_id, authority_id)
                REFERENCES corpus.legal_authorities(scope_id, id),
            CONSTRAINT legal_instrument_authority_roles_unique
                UNIQUE NULLS NOT DISTINCT (instrument_id, authority_id, authority_role, valid_from)
        )
        """
    )

    # A provision can continue, split, merge, be renumbered or be replaced.
    op.execute(
        f"""
        CREATE TABLE corpus.legal_provision_lineage (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            from_provision_id uuid NOT NULL,
            to_provision_id uuid NOT NULL,
            lineage_type text NOT NULL,
            effective_on date,
            amendment_effect_id uuid REFERENCES corpus.legal_amendment_effects(id) ON DELETE SET NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_provision_lineage_distinct_check CHECK (from_provision_id <> to_provision_id),
            CONSTRAINT legal_provision_lineage_type_check CHECK (
                lineage_type IN (
                    'continues_as', 'renumbered_as', 'split_into', 'merged_into',
                    'replaced_by', 'transferred_to', 'derived_from'
                )
            ),
            CONSTRAINT legal_provision_lineage_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_provision_lineage_from_scope_fkey
                FOREIGN KEY (scope_id, from_provision_id)
                REFERENCES corpus.legal_provisions(scope_id, id),
            CONSTRAINT legal_provision_lineage_to_scope_fkey
                FOREIGN KEY (scope_id, to_provision_id)
                REFERENCES corpus.legal_provisions(scope_id, id),
            CONSTRAINT legal_provision_lineage_unique
                UNIQUE NULLS NOT DISTINCT (from_provision_id, to_provision_id, lineage_type, effective_on)
        )
        """
    )

    # Exact amendment reconstruction is anchored to a specific target version;
    # offsets therefore have a stable text coordinate system.
    op.execute(
        f"""
        CREATE TABLE corpus.legal_amendment_operations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            amendment_effect_id uuid NOT NULL
                REFERENCES corpus.legal_amendment_effects(id) ON DELETE CASCADE,
            target_provision_version_id uuid NOT NULL,
            sequence_number integer NOT NULL,
            operation_type text NOT NULL,
            char_start integer,
            char_end integer,
            anchor_text text,
            replacement_text text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_amendment_operations_sequence_check CHECK (sequence_number > 0),
            CONSTRAINT legal_amendment_operations_type_check CHECK (
                operation_type IN ('insert', 'delete', 'replace', 'move', 'renumber', 'whole_provision_replace')
            ),
            CONSTRAINT legal_amendment_operations_offsets_check CHECK (
                (char_start IS NULL AND char_end IS NULL)
                OR (char_start IS NOT NULL AND char_end IS NOT NULL AND char_start >= 0 AND char_end >= char_start)
            ),
            CONSTRAINT legal_amendment_operations_anchor_check CHECK (
                char_start IS NOT NULL OR btrim(coalesce(anchor_text, '')) <> ''
                OR operation_type IN ('renumber', 'whole_provision_replace')
            ),
            CONSTRAINT legal_amendment_operations_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_amendment_operations_same_scope_target_fkey
                FOREIGN KEY (scope_id, target_provision_version_id)
                REFERENCES corpus.legal_provision_versions(scope_id, id),
            CONSTRAINT legal_amendment_operations_unique
                UNIQUE (amendment_effect_id, sequence_number)
        )
        """
    )

    # Normalized party roles are separate from raw participant capture.  One
    # participant may occupy different procedural roles over time/proceedings.
    op.execute(
        f"""
        CREATE TABLE corpus.proceeding_party_roles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proceeding_id uuid NOT NULL,
            participant_id uuid NOT NULL,
            role_type text NOT NULL,
            party_side text NOT NULL DEFAULT 'other',
            raw_role text,
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT proceeding_party_roles_type_check CHECK (
                role_type IN (
                    'plaintiff', 'defendant', 'appellant', 'appellee', 'petitioner',
                    'respondent', 'claimant', 'complainant', 'accused', 'prosecutor',
                    'public_ministry', 'intervenor', 'third_party', 'amicus', 'other'
                )
            ),
            CONSTRAINT proceeding_party_roles_side_check CHECK (
                party_side IN ('claimant', 'respondent', 'neutral', 'state', 'other')
            ),
            CONSTRAINT proceeding_party_roles_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT proceeding_party_roles_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT proceeding_party_roles_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT proceeding_party_roles_same_scope_participant_fkey
                FOREIGN KEY (scope_id, participant_id)
                REFERENCES corpus.participants(scope_id, id),
            CONSTRAINT proceeding_party_roles_unique
                UNIQUE NULLS NOT DISTINCT (proceeding_id, participant_id, role_type, valid_from)
        )
        """
    )
    op.execute(
        "CREATE INDEX proceeding_party_roles_proceeding_idx "
        "ON corpus.proceeding_party_roles (scope_id, proceeding_id, role_type)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.party_representations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            party_role_id uuid NOT NULL,
            representative_participant_id uuid NOT NULL,
            representation_type text NOT NULL,
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT party_representations_type_check CHECK (
                representation_type IN (
                    'counsel', 'lead_counsel', 'public_defender', 'attorney_in_fact',
                    'government_counsel', 'guardian_ad_litem', 'self_represented', 'other'
                )
            ),
            CONSTRAINT party_representations_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT party_representations_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT party_representations_same_scope_role_fkey
                FOREIGN KEY (scope_id, party_role_id)
                REFERENCES corpus.proceeding_party_roles(scope_id, id),
            CONSTRAINT party_representations_same_scope_representative_fkey
                FOREIGN KEY (scope_id, representative_participant_id)
                REFERENCES corpus.participants(scope_id, id),
            CONSTRAINT party_representations_unique
                UNIQUE NULLS NOT DISTINCT (party_role_id, representative_participant_id, representation_type, valid_from)
        )
        """
    )
    op.execute(
        "ALTER TABLE corpus.proceeding_party_roles "
        "ADD CONSTRAINT proceeding_party_roles_scope_id_id_key UNIQUE (scope_id, id)"
    )

    # Panel membership says who sat.  Vote/opinion tables say what each judge
    # decided or authored. Remove stance-like values from panel_role.
    op.execute("ALTER TABLE corpus.decision_panel_members DROP CONSTRAINT decision_panel_members_role_check")
    op.execute(
        """
        ALTER TABLE corpus.decision_panel_members
        ADD CONSTRAINT decision_panel_members_role_check CHECK (
            panel_role IN ('presiding', 'rapporteur', 'ponente', 'member', 'other')
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.judicial_officer_positions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            officer_id uuid NOT NULL,
            court_id uuid NOT NULL REFERENCES corpus.courts(id),
            position_type text NOT NULL,
            title_raw text,
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_officer_positions_type_check CHECK (
                position_type IN ('judge', 'chief_judge', 'president', 'vice_president', 'substitute', 'emeritus', 'other')
            ),
            CONSTRAINT judicial_officer_positions_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT judicial_officer_positions_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT judicial_officer_positions_same_scope_officer_fkey
                FOREIGN KEY (scope_id, officer_id)
                REFERENCES corpus.judicial_officers(scope_id, id),
            CONSTRAINT judicial_officer_positions_unique
                UNIQUE NULLS NOT DISTINCT (officer_id, court_id, position_type, valid_from)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.judicial_opinions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            case_id uuid NOT NULL,
            opinion_type text NOT NULL,
            author_officer_id uuid,
            document_id uuid,
            proposition_id uuid,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_opinions_type_check CHECK (
                opinion_type IN ('majority', 'plurality', 'per_curiam', 'concurring', 'dissenting', 'concurring_in_result', 'separate')
            ),
            CONSTRAINT judicial_opinions_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT judicial_opinions_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT judicial_opinions_same_scope_author_fkey
                FOREIGN KEY (scope_id, author_officer_id) REFERENCES corpus.judicial_officers(scope_id, id),
            CONSTRAINT judicial_opinions_same_scope_document_fkey
                FOREIGN KEY (scope_id, document_id) REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT judicial_opinions_same_scope_proposition_fkey
                FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT judicial_opinions_author_shape_check CHECK (
                opinion_type = 'per_curiam' OR author_officer_id IS NOT NULL
            ),
            CONSTRAINT judicial_opinions_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.judicial_opinion_joiners (
            opinion_id uuid NOT NULL,
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            officer_id uuid NOT NULL,
            join_type text NOT NULL DEFAULT 'joins_all',
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (opinion_id, officer_id, join_type),
            CONSTRAINT judicial_opinion_joiners_type_check CHECK (
                join_type IN ('joins_all', 'joins_part', 'concurs_in_result', 'dissents_in_part')
            ),
            CONSTRAINT judicial_opinion_joiners_same_scope_opinion_fkey
                FOREIGN KEY (scope_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, id),
            CONSTRAINT judicial_opinion_joiners_same_scope_officer_fkey
                FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE corpus.decision_votes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            case_id uuid NOT NULL,
            officer_id uuid NOT NULL,
            vote_type text NOT NULL,
            opinion_id uuid,
            note text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_votes_type_check CHECK (
                vote_type IN ('majority', 'plurality', 'concurring', 'dissenting', 'concurs_in_result', 'abstained', 'not_participating')
            ),
            CONSTRAINT decision_votes_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT decision_votes_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT decision_votes_same_scope_officer_fkey
                FOREIGN KEY (scope_id, officer_id) REFERENCES corpus.judicial_officers(scope_id, id),
            CONSTRAINT decision_votes_same_scope_opinion_fkey
                FOREIGN KEY (scope_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, id),
            CONSTRAINT decision_votes_unique UNIQUE (case_id, officer_id)
        )
        """
    )

    # Legal finality/effect is not corpus review quality and changes over time.
    op.execute(
        f"""
        CREATE TABLE corpus.decision_legal_status_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            case_id uuid NOT NULL,
            status_type text NOT NULL,
            occurred_on date,
            date_status text NOT NULL DEFAULT 'unknown',
            source_document_id uuid,
            evidence_case_page_id uuid,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_legal_status_events_type_check CHECK (
                status_type IN (
                    'issued', 'notified', 'appealable', 'final', 'res_judicata', 'stayed',
                    'suspended', 'vacated', 'annulled', 'reversed', 'partially_reversed',
                    'enforced', 'superseded', 'other'
                )
            ),
            CONSTRAINT decision_legal_status_events_date_status_check CHECK (
                date_status IN ('verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence', 'parsed_unverified', 'conflicting', 'unknown')
            ),
            CONSTRAINT decision_legal_status_events_verified_date_requires_date CHECK (
                date_status NOT IN ('verified_primary_text', 'verified_official_metadata', 'parsed_high_confidence')
                OR occurred_on IS NOT NULL
            ),
            CONSTRAINT decision_legal_status_events_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT decision_legal_status_events_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT decision_legal_status_events_same_scope_document_fkey
                FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT decision_legal_status_events_same_case_evidence_fkey
                FOREIGN KEY (case_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX decision_legal_status_events_timeline_idx "
        "ON corpus.decision_legal_status_events (scope_id, case_id, occurred_on, created_at)"
    )

    # Precedential authority is contextual: a decision can be binding for one
    # court/jurisdiction/issue and merely persuasive elsewhere.
    op.execute(
        f"""
        CREATE TABLE corpus.precedential_authority_assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            decision_id uuid NOT NULL,
            proposition_id uuid,
            authority_type text NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            court_id uuid REFERENCES corpus.courts(id),
            legal_matter_concept_id uuid REFERENCES corpus.legal_matter_concepts(id),
            valid_from date,
            valid_to date,
            basis text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT precedential_authority_assertions_type_check CHECK (
                authority_type IN ('binding', 'persuasive', 'nonbinding', 'superseded', 'abrogated', 'unknown')
            ),
            CONSTRAINT precedential_authority_assertions_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT precedential_authority_assertions_context_check CHECK (
                jurisdiction_code IS NOT NULL OR court_id IS NOT NULL OR legal_matter_concept_id IS NOT NULL
            ),
            CONSTRAINT precedential_authority_assertions_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT precedential_authority_assertions_same_scope_decision_fkey
                FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT precedential_authority_assertions_same_scope_proposition_fkey
                FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id)
        )
        """
    )

    # Substantive treatment is a legal assertion, not a timeless document edge.
    op.execute(
        f"""
        CREATE TABLE corpus.legal_treatment_assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            source_case_id uuid NOT NULL,
            target_case_id uuid NOT NULL,
            treatment_type text NOT NULL,
            issue_proposition_id uuid,
            source_proposition_id uuid,
            target_proposition_id uuid,
            evidence_id uuid REFERENCES corpus.legal_proposition_evidence(id),
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_treatment_assertions_distinct_check CHECK (source_case_id <> target_case_id),
            CONSTRAINT legal_treatment_assertions_type_check CHECK (
                treatment_type IN (
                    'cites', 'references', 'interprets', 'applies', 'declines_to_apply',
                    'follows', 'distinguishes', 'limits', 'questions', 'criticizes',
                    'overrules', 'abrogates', 'conflicts_with', 'consistent_with'
                )
            ),
            CONSTRAINT legal_treatment_assertions_context_check CHECK (
                treatment_type IN ('cites', 'references') OR issue_proposition_id IS NOT NULL
            ),
            CONSTRAINT legal_treatment_assertions_range_check
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_treatment_assertions_status_check
                CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_treatment_assertions_same_scope_source_case_fkey
                FOREIGN KEY (scope_id, source_case_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT legal_treatment_assertions_same_scope_target_case_fkey
                FOREIGN KEY (scope_id, target_case_id) REFERENCES corpus.cases(scope_id, id),
            CONSTRAINT legal_treatment_assertions_same_scope_issue_fkey
                FOREIGN KEY (scope_id, issue_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_treatment_assertions_same_scope_source_prop_fkey
                FOREIGN KEY (scope_id, source_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_treatment_assertions_same_scope_target_prop_fkey
                FOREIGN KEY (scope_id, target_proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_treatment_assertions_unique
                UNIQUE NULLS NOT DISTINCT (
                    source_case_id, target_case_id, treatment_type,
                    issue_proposition_id, source_proposition_id, target_proposition_id
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_treatment_assertions_source_idx "
        "ON corpus.legal_treatment_assertions (scope_id, source_case_id, treatment_type)"
    )
    op.execute(
        "CREATE INDEX legal_treatment_assertions_target_idx "
        "ON corpus.legal_treatment_assertions (scope_id, target_case_id, treatment_type)"
    )

    # Canonical document relations are now structural/citation facts only.
    # Context-dependent judicial treatments live in legal_treatment_assertions.
    op.execute("ALTER TABLE corpus.legal_relations DROP CONSTRAINT legal_relations_type_check")
    op.execute(
        """
        ALTER TABLE corpus.legal_relations
        ADD CONSTRAINT legal_relations_type_check CHECK (
            relation_type IN (
                'cites', 'references', 'authorized_by', 'implements', 'amends',
                'repeals', 'partially_repeals', 'supersedes', 'requires',
                'satisfies', 'exempts_from'
            )
        )
        """
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.legal_instrument_version_knowledge IS
        'Bitemporal assertions about a juridical instrument version: valid_* is legal time; known_* is JurisNexo system/knowledge time. Corrections append history instead of rewriting it.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_provision_version_knowledge IS
        'Bitemporal text/heading knowledge for a stable provision version. Source corrections preserve what was known at earlier system times.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_treatment_assertions IS
        'Contextual judicial treatment between decisions/propositions. Substantive treatments require an issue proposition and must not be represented as timeless global document relations.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.decision_legal_status_events IS
        'Legal effect/finality history of a judicial decision. This is independent from corpus extraction/review quality.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.proceeding_participants.role_normalized IS
        'Legacy/raw normalization aid only. Canonical procedural roles belong in proceeding_party_roles.'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE corpus.legal_relations DROP CONSTRAINT IF EXISTS legal_relations_type_check")
    op.execute(
        """
        ALTER TABLE corpus.legal_relations
        ADD CONSTRAINT legal_relations_type_check CHECK (
            relation_type IN (
                'cites', 'references', 'interprets', 'applies', 'declines_to_apply',
                'follows', 'distinguishes', 'overrules', 'authorized_by', 'implements',
                'amends', 'repeals', 'partially_repeals', 'supersedes', 'conflicts_with',
                'consistent_with', 'requires', 'satisfies', 'exempts_from'
            )
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS corpus.legal_treatment_assertions")
    op.execute("DROP TABLE IF EXISTS corpus.precedential_authority_assertions")
    op.execute("DROP TABLE IF EXISTS corpus.decision_legal_status_events")
    op.execute("DROP TABLE IF EXISTS corpus.decision_votes")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_opinion_joiners")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_opinions")
    op.execute("DROP TABLE IF EXISTS corpus.judicial_officer_positions")
    op.execute("ALTER TABLE corpus.decision_panel_members DROP CONSTRAINT IF EXISTS decision_panel_members_role_check")
    op.execute(
        """
        ALTER TABLE corpus.decision_panel_members
        ADD CONSTRAINT decision_panel_members_role_check CHECK (
            panel_role IN ('presiding', 'rapporteur', 'ponente', 'member', 'dissenting', 'concurring', 'other')
        )
        """
    )
    op.execute("DROP TABLE IF EXISTS corpus.party_representations")
    op.execute("DROP TABLE IF EXISTS corpus.proceeding_party_roles")
    op.execute("DROP TABLE IF EXISTS corpus.legal_amendment_operations")
    op.execute("DROP TABLE IF EXISTS corpus.legal_provision_lineage")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_authority_roles")
    op.execute("DROP TABLE IF EXISTS corpus.legal_authorities")
    op.execute("DROP TABLE IF EXISTS corpus.legal_provision_version_knowledge")
    op.execute("DROP TABLE IF EXISTS corpus.legal_instrument_version_knowledge")
    op.execute("DROP TABLE IF EXISTS corpus.procedure_concept_edges")
    op.execute("DROP TABLE IF EXISTS corpus.legal_matter_concept_edges")
    op.execute("ALTER TABLE corpus.procedure_concepts ADD COLUMN parent_id uuid REFERENCES corpus.procedure_concepts(id)")
    op.execute("ALTER TABLE corpus.legal_matter_concepts ADD COLUMN parent_id uuid REFERENCES corpus.legal_matter_concepts(id)")
    op.execute(
        "CREATE INDEX procedure_concepts_parent_idx ON corpus.procedure_concepts (parent_id) WHERE parent_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX legal_matter_concepts_parent_idx ON corpus.legal_matter_concepts (parent_id) WHERE parent_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.legal_provision_versions DROP CONSTRAINT IF EXISTS legal_provision_versions_scope_id_id_key"
    )
