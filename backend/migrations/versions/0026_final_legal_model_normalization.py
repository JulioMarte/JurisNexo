"""Normalize final pre-ingestion legal identities and assertions.

Revision ID: 0026_final_legal_model
Revises: 0025_harden_semantics
Create Date: 2026-09-16

The corpus is intentionally empty. This revision removes the last legacy
abstractions that would be expensive to correct after mass ingestion.
"""

from alembic import op

revision = "0026_final_legal_model"
down_revision = "0025_harden_semantics"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute("ALTER TABLE corpus.cases RENAME TO judicial_decisions")
    op.execute("CREATE VIEW corpus.cases AS SELECT * FROM corpus.judicial_decisions")
    op.execute(
        "COMMENT ON VIEW corpus.cases IS "
        "'Deprecated compatibility view. Canonical physical identity is corpus.judicial_decisions.'"
    )
    op.execute(
        "COMMENT ON TABLE corpus.judicial_decisions IS "
        "'One judicial decision. It is distinct from a controversy, proceeding, publication and source artifact.'"
    )

    op.execute(
        """
        CREATE TABLE corpus.disposition_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            broader_concept_id uuid REFERENCES corpus.disposition_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT disposition_concepts_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT disposition_concepts_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT disposition_concepts_not_self_parent CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.disposition_concepts (code, name) VALUES
        ('granted', 'Granted'), ('denied', 'Denied'), ('dismissed', 'Dismissed'),
        ('inadmissible', 'Inadmissible'), ('affirmed', 'Affirmed'),
        ('reversed', 'Reversed'), ('vacated', 'Vacated'), ('modified', 'Modified'),
        ('remanded', 'Remanded'), ('cassated', 'Cassated'),
        ('partially_cassated', 'Partially cassated'), ('costs', 'Costs'), ('other', 'Other')
        """
    )
    op.execute("ALTER TABLE corpus.case_dispositions ADD COLUMN disposition_concept_id uuid")
    op.execute(
        """
        UPDATE corpus.case_dispositions d
        SET disposition_concept_id = c.id
        FROM corpus.disposition_concepts c
        WHERE c.code = d.disposition_type
        """
    )
    op.execute("ALTER TABLE corpus.case_dispositions ALTER COLUMN disposition_concept_id SET NOT NULL")
    op.execute(
        "ALTER TABLE corpus.case_dispositions ADD CONSTRAINT case_dispositions_concept_fkey "
        "FOREIGN KEY (disposition_concept_id) REFERENCES corpus.disposition_concepts(id)"
    )
    op.execute("ALTER TABLE corpus.case_dispositions DROP CONSTRAINT case_dispositions_type_check")
    op.execute("ALTER TABLE corpus.case_dispositions DROP COLUMN disposition_type")
    op.execute("ALTER TABLE corpus.case_dispositions RENAME TO judicial_decision_dispositions")
    op.execute("CREATE VIEW corpus.case_dispositions AS SELECT * FROM corpus.judicial_decision_dispositions")

    op.execute(
        """
        CREATE TABLE corpus.procedural_role_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            default_party_side text NOT NULL DEFAULT 'other',
            broader_concept_id uuid REFERENCES corpus.procedural_role_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT procedural_role_concepts_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT procedural_role_concepts_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT procedural_role_concepts_side_check CHECK (default_party_side IN ('claimant', 'respondent', 'neutral', 'state', 'other')),
            CONSTRAINT procedural_role_concepts_not_self_parent CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.procedural_role_concepts (code, name, default_party_side) VALUES
        ('plaintiff', 'Plaintiff', 'claimant'), ('defendant', 'Defendant', 'respondent'),
        ('appellant', 'Appellant / recurrente', 'claimant'), ('appellee', 'Appellee / recurrido', 'respondent'),
        ('petitioner', 'Petitioner / accionante', 'claimant'), ('respondent', 'Respondent / accionado', 'respondent'),
        ('claimant', 'Claimant', 'claimant'), ('complainant', 'Complainant / querellante', 'claimant'),
        ('accused', 'Accused / imputado', 'respondent'), ('prosecutor', 'Prosecutor', 'state'),
        ('public_ministry', 'Ministerio Público', 'state'), ('intervenor', 'Intervenor', 'neutral'),
        ('third_party', 'Third party', 'other'), ('amicus', 'Amicus curiae', 'neutral'), ('other', 'Other', 'other')
        """
    )
    op.execute("ALTER TABLE corpus.proceeding_party_roles ADD COLUMN role_concept_id uuid")
    op.execute(
        """
        UPDATE corpus.proceeding_party_roles r
        SET role_concept_id = c.id
        FROM corpus.procedural_role_concepts c
        WHERE c.code = r.role_type
        """
    )
    op.execute("ALTER TABLE corpus.proceeding_party_roles ALTER COLUMN role_concept_id SET NOT NULL")
    op.execute(
        "ALTER TABLE corpus.proceeding_party_roles ADD CONSTRAINT proceeding_party_roles_concept_fkey "
        "FOREIGN KEY (role_concept_id) REFERENCES corpus.procedural_role_concepts(id)"
    )
    op.execute("ALTER TABLE corpus.proceeding_party_roles DROP CONSTRAINT proceeding_party_roles_type_check")
    op.execute("ALTER TABLE corpus.proceeding_party_roles DROP CONSTRAINT proceeding_party_roles_unique")
    op.execute("ALTER TABLE corpus.proceeding_party_roles DROP COLUMN role_type")
    op.execute(
        "ALTER TABLE corpus.proceeding_party_roles ADD CONSTRAINT proceeding_party_roles_unique "
        "UNIQUE NULLS NOT DISTINCT (proceeding_id, participant_id, role_concept_id, valid_from)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_proposition_subjects (
            proposition_id uuid NOT NULL,
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            subject_type text NOT NULL,
            judicial_decision_id uuid,
            legal_document_id uuid,
            proceeding_id uuid,
            provision_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (proposition_id, subject_type),
            CONSTRAINT legal_proposition_subjects_type_check CHECK (subject_type IN ('judicial_decision', 'legal_document', 'proceeding', 'provision', 'general_law')),
            CONSTRAINT legal_proposition_subjects_shape_check CHECK (
                (subject_type = 'judicial_decision' AND judicial_decision_id IS NOT NULL AND legal_document_id IS NULL AND proceeding_id IS NULL AND provision_id IS NULL) OR
                (subject_type = 'legal_document' AND judicial_decision_id IS NULL AND legal_document_id IS NOT NULL AND proceeding_id IS NULL AND provision_id IS NULL) OR
                (subject_type = 'proceeding' AND judicial_decision_id IS NULL AND legal_document_id IS NULL AND proceeding_id IS NOT NULL AND provision_id IS NULL) OR
                (subject_type = 'provision' AND judicial_decision_id IS NULL AND legal_document_id IS NULL AND proceeding_id IS NULL AND provision_id IS NOT NULL) OR
                (subject_type = 'general_law' AND judicial_decision_id IS NULL AND legal_document_id IS NULL AND proceeding_id IS NULL AND provision_id IS NULL)
            ),
            CONSTRAINT legal_proposition_subjects_same_scope_prop_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_proposition_subjects_same_scope_decision_fkey FOREIGN KEY (scope_id, judicial_decision_id) REFERENCES corpus.judicial_decisions(scope_id, id),
            CONSTRAINT legal_proposition_subjects_same_scope_document_fkey FOREIGN KEY (scope_id, legal_document_id) REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_proposition_subjects_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT legal_proposition_subjects_same_scope_provision_fkey FOREIGN KEY (scope_id, provision_id) REFERENCES corpus.legal_provisions(scope_id, id)
        )
        """
    )

    op.execute("DROP TABLE corpus.legal_requirement_sources")
    op.execute("DROP TABLE corpus.legal_requirements")
    op.execute("ALTER TABLE corpus.legal_propositions DROP CONSTRAINT legal_propositions_type_check")
    op.execute(
        """
        ALTER TABLE corpus.legal_propositions ADD CONSTRAINT legal_propositions_type_check CHECK (
            proposition_type IN ('issue', 'holding', 'legal_rule', 'legal_test', 'legal_requirement',
                                 'exception', 'material_fact', 'procedural_fact', 'argument',
                                 'counterargument', 'reasoning', 'conclusion', 'dictum', 'other')
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE corpus.legal_norm_assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proposition_id uuid NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            norm_kind text NOT NULL,
            derivation_kind text NOT NULL,
            valid_from date,
            valid_to date,
            known_from timestamptz NOT NULL DEFAULT now(),
            known_to timestamptz,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            reviewed_by text,
            review_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_norm_assertions_kind_check CHECK (btrim(norm_kind) <> ''),
            CONSTRAINT legal_norm_assertions_derivation_check CHECK (derivation_kind IN ('explicit_primary_text', 'derived_from_sources', 'synthesized_interpretation', 'human_legal_analysis')),
            CONSTRAINT legal_norm_assertions_valid_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_norm_assertions_known_range_check CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT legal_norm_assertions_status_check CHECK (verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_norm_assertions_same_scope_prop_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_norm_assertions_unique UNIQUE (proposition_id, known_from)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_norm_assertions_current_idx ON corpus.legal_norm_assertions (proposition_id) WHERE known_to IS NULL"
    )

    op.execute("DROP TABLE corpus.legal_relation_evidence")
    op.execute("DROP TABLE corpus.legal_relations")
    op.execute(
        """
        CREATE TABLE corpus.legal_relation_identities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            source_provision_id uuid,
            relation_type text NOT NULL,
            target_document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            target_provision_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relation_identities_type_check CHECK (relation_type IN ('cites', 'references', 'authorized_by', 'implements', 'amends', 'repeals', 'partially_repeals', 'supersedes', 'requires', 'satisfies', 'exempts_from')),
            CONSTRAINT legal_relation_identities_distinct_check CHECK (source_document_id <> target_document_id OR source_provision_id IS DISTINCT FROM target_provision_id),
            CONSTRAINT legal_relation_identities_source_provision_fkey FOREIGN KEY (source_document_id, source_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id),
            CONSTRAINT legal_relation_identities_target_provision_fkey FOREIGN KEY (target_document_id, target_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id)
        )
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX legal_relation_identities_key ON corpus.legal_relation_identities (
            source_document_id, coalesce(source_provision_id, '{ZERO_UUID}'::uuid), relation_type,
            target_document_id, coalesce(target_provision_id, '{ZERO_UUID}'::uuid)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_relation_assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            relation_identity_id uuid NOT NULL REFERENCES corpus.legal_relation_identities(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'verified',
            valid_from date,
            valid_to date,
            known_from timestamptz NOT NULL DEFAULT now(),
            known_to timestamptz,
            verification_method text NOT NULL,
            reviewed_by text,
            promoted_from_observation_id uuid REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relation_assertions_status_check CHECK (status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')),
            CONSTRAINT legal_relation_assertions_valid_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_relation_assertions_known_range_check CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT legal_relation_assertions_unique UNIQUE (relation_identity_id, known_from)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_relation_assertions_current_idx ON corpus.legal_relation_assertions (relation_identity_id) WHERE known_to IS NULL"
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_relation_assertion_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            assertion_id uuid NOT NULL REFERENCES corpus.legal_relation_assertions(id) ON DELETE CASCADE,
            observation_id uuid REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_kind text NOT NULL,
            evidence_excerpt text,
            evidence_char_start integer,
            evidence_char_end integer,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relation_assertion_evidence_kind_check CHECK (evidence_kind IN ('primary_text', 'official_metadata', 'deterministic_match', 'manual_review')),
            CONSTRAINT legal_relation_assertion_evidence_presence_check CHECK (observation_id IS NOT NULL OR artifact_page_id IS NOT NULL),
            CONSTRAINT legal_relation_assertion_evidence_offsets_check CHECK ((evidence_char_start IS NULL AND evidence_char_end IS NULL) OR (evidence_char_start IS NOT NULL AND evidence_char_end IS NOT NULL AND evidence_char_start >= 0 AND evidence_char_end > evidence_char_start))
        )
        """
    )

    op.execute("ALTER TABLE corpus.legal_treatment_assertions ADD COLUMN known_from timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE corpus.legal_treatment_assertions ADD COLUMN known_to timestamptz")
    op.execute("ALTER TABLE corpus.legal_treatment_assertions DROP CONSTRAINT legal_treatment_assertions_unique")
    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions ADD CONSTRAINT legal_treatment_assertions_known_range_check CHECK (known_to IS NULL OR known_to > known_from)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions ADD CONSTRAINT legal_treatment_assertions_verified_evidence_check CHECK (verification_status <> 'verified' OR treatment_type IN ('cites', 'references') OR evidence_id IS NOT NULL)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX legal_treatment_assertions_current_idx
        ON corpus.legal_treatment_assertions (
            source_case_id, target_case_id, treatment_type,
            coalesce(issue_proposition_id, '00000000-0000-0000-0000-000000000000'::uuid),
            coalesce(source_proposition_id, '00000000-0000-0000-0000-000000000000'::uuid),
            coalesce(target_proposition_id, '00000000-0000-0000-0000-000000000000'::uuid)
        ) WHERE known_to IS NULL
        """
    )
    op.execute(
        """
        CREATE FUNCTION corpus.validate_treatment_proposition_membership() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.source_proposition_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_subjects s
                WHERE s.proposition_id = NEW.source_proposition_id
                  AND s.subject_type = 'judicial_decision'
                  AND s.judicial_decision_id = NEW.source_case_id
            ) THEN RAISE EXCEPTION 'source proposition does not belong to source judicial decision' USING ERRCODE='23514'; END IF;
            IF NEW.target_proposition_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_subjects s
                WHERE s.proposition_id = NEW.target_proposition_id
                  AND s.subject_type = 'judicial_decision'
                  AND s.judicial_decision_id = NEW.target_case_id
            ) THEN RAISE EXCEPTION 'target proposition does not belong to target judicial decision' USING ERRCODE='23514'; END IF;
            IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_proposition_evidence e
                WHERE e.id = NEW.evidence_id AND e.source_case_id = NEW.source_case_id
            ) THEN RAISE EXCEPTION 'treatment evidence must belong to source judicial decision' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_treatment_assertions_membership BEFORE INSERT OR UPDATE ON corpus.legal_treatment_assertions FOR EACH ROW EXECUTE FUNCTION corpus.validate_treatment_proposition_membership()"
    )

    op.execute("ALTER TABLE corpus.judicial_opinion_joiners ADD COLUMN case_id uuid")
    op.execute(
        """
        UPDATE corpus.judicial_opinion_joiners j
        SET case_id = o.case_id FROM corpus.judicial_opinions o WHERE o.id = j.opinion_id
        """
    )
    op.execute("ALTER TABLE corpus.judicial_opinion_joiners ALTER COLUMN case_id SET NOT NULL")
    op.execute(
        "ALTER TABLE corpus.judicial_opinion_joiners ADD CONSTRAINT judicial_opinion_joiners_same_case_opinion_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinion_joiners ADD CONSTRAINT judicial_opinion_joiners_panel_member_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id)"
    )

    op.execute(
        """
        CREATE TABLE corpus.territorial_units (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            unit_type text NOT NULL,
            parent_id uuid REFERENCES corpus.territorial_units(id),
            country_code character(2) NOT NULL DEFAULT 'DO',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT territorial_units_type_check CHECK (unit_type IN ('country', 'province', 'municipality', 'district', 'judicial_district', 'region', 'other')),
            CONSTRAINT territorial_units_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT territorial_units_not_self_parent CHECK (parent_id IS NULL OR parent_id <> id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.court_territorial_competences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            territorial_unit_id uuid NOT NULL REFERENCES corpus.territorial_units(id),
            valid_from date, valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate', verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_territorial_competences_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT court_territorial_competences_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT court_territorial_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, territorial_unit_id, valid_from)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.court_subject_matter_competences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            legal_matter_concept_id uuid NOT NULL REFERENCES corpus.legal_matter_concepts(id),
            valid_from date, valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate', verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_subject_matter_competences_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT court_subject_matter_competences_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT court_subject_matter_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, legal_matter_concept_id, valid_from)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.court_functional_competences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            function_type text NOT NULL,
            instance_level text NOT NULL,
            procedure_concept_id uuid REFERENCES corpus.procedure_concepts(id),
            valid_from date, valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate', verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_functional_competences_function_check CHECK (function_type IN ('original', 'appellate', 'cassation', 'constitutional_review', 'electoral_review', 'execution', 'administrative_review', 'other')),
            CONSTRAINT court_functional_competences_instance_check CHECK (instance_level IN ('first', 'second', 'supreme', 'special', 'not_applicable', 'other')),
            CONSTRAINT court_functional_competences_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT court_functional_competences_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT court_functional_competences_unique UNIQUE NULLS NOT DISTINCT (court_id, function_type, instance_level, procedure_concept_id, valid_from)
        )
        """
    )

    op.execute("ALTER TABLE corpus.precedential_authority_assertions ADD COLUMN known_from timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE corpus.precedential_authority_assertions ADD COLUMN known_to timestamptz")
    op.execute("ALTER TABLE corpus.precedential_authority_assertions ADD CONSTRAINT precedential_authority_known_range_check CHECK (known_to IS NULL OR known_to > known_from)")
    op.execute("ALTER TABLE corpus.decision_legal_status_events ADD COLUMN known_from timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE corpus.decision_legal_status_events ADD COLUMN known_to timestamptz")
    op.execute("ALTER TABLE corpus.decision_legal_status_events ADD CONSTRAINT decision_legal_status_known_range_check CHECK (known_to IS NULL OR known_to > known_from)")
    op.execute("ALTER TABLE corpus.legal_proposition_relations DROP CONSTRAINT legal_proposition_relations_type_check")
    op.execute(
        """
        ALTER TABLE corpus.legal_proposition_relations ADD CONSTRAINT legal_proposition_relations_type_check CHECK (
            relation_type IN ('answers','supports','opposes','qualifies','limits','creates_exception_to',
                              'depends_on','derived_from','applies_to','distinguishes_from','supersedes','contradicts')
        )
        """
    )

    op.execute("COMMENT ON TABLE corpus.legal_norm_assertions IS 'Epistemic and temporal assertion that a legal proposition functions as a norm/requirement; the proposition text is not treated as promulgated canonical text unless evidence says so.'")
    op.execute("COMMENT ON TABLE corpus.legal_relation_assertions IS 'Time- and knowledge-bounded assertion over a stable structural legal relation identity.'")
    op.execute("COMMENT ON TABLE corpus.legal_proposition_subjects IS 'Binds a proposition to the decision, document, proceeding or stable provision it actually describes.'")


def downgrade() -> None:
    raise RuntimeError(
        "0026 is an intentional pre-ingestion normalization boundary "
        "and is not safely downgradeable"
    )
