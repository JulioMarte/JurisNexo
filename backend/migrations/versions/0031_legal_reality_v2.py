"""Harden legal reality cardinalities and identities before mass ingestion.

Revision ID: 0031_legal_reality_v2
Revises: 0030_verified_norm_sources
Create Date: 2026-09-16

This revision keeps the existing pre-ingestion architecture but removes several
false singularities that do not hold in real litigation: propositions may have
multiple subjects of the same type, decisions may address multiple matters and
proceedings, judicial positions may be partial, opinions may have multiple
authors, normative claims are distinct from proposition text, and claims sought
by parties are first-class objects.
"""

from alembic import op

revision = "0031_legal_reality_v2"
down_revision = "0030_verified_norm_sources"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    _proposition_subject_cardinality()
    _immutable_proposition_identity()
    _decision_multi_classification()
    _controversy_and_proceeding_cardinality()
    _opinion_authorship_and_vote_stances()
    _legal_entity_identity()
    _claims_and_disposition_effects()
    _norm_claim_identity()
    _decision_legal_states()


def _proposition_subject_cardinality() -> None:
    op.execute("ALTER TABLE corpus.legal_proposition_subjects ADD COLUMN id uuid DEFAULT gen_random_uuid()")
    op.execute("UPDATE corpus.legal_proposition_subjects SET id = gen_random_uuid() WHERE id IS NULL")
    op.execute("ALTER TABLE corpus.legal_proposition_subjects ALTER COLUMN id SET NOT NULL")
    op.execute("ALTER TABLE corpus.legal_proposition_subjects ADD COLUMN subject_role text NOT NULL DEFAULT 'about'")
    op.execute("ALTER TABLE corpus.legal_proposition_subjects ADD COLUMN ordinal integer")
    op.execute(
        "ALTER TABLE corpus.legal_proposition_subjects ADD CONSTRAINT legal_proposition_subjects_role_nonempty CHECK (btrim(subject_role) <> '')"
    )
    op.execute(
        "ALTER TABLE corpus.legal_proposition_subjects ADD CONSTRAINT legal_proposition_subjects_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0)"
    )
    op.execute("ALTER TABLE corpus.legal_proposition_subjects DROP CONSTRAINT legal_proposition_subjects_pkey")
    op.execute("ALTER TABLE corpus.legal_proposition_subjects ADD PRIMARY KEY (id)")
    op.execute(
        "CREATE UNIQUE INDEX legal_proposition_subjects_decision_key ON corpus.legal_proposition_subjects (proposition_id, subject_role, judicial_decision_id) WHERE judicial_decision_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_proposition_subjects_document_key ON corpus.legal_proposition_subjects (proposition_id, subject_role, legal_document_id) WHERE legal_document_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_proposition_subjects_proceeding_key ON corpus.legal_proposition_subjects (proposition_id, subject_role, proceeding_id) WHERE proceeding_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_proposition_subjects_provision_key ON corpus.legal_proposition_subjects (proposition_id, subject_role, provision_id) WHERE provision_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_proposition_subjects_general_law_key ON corpus.legal_proposition_subjects (proposition_id, subject_role) WHERE subject_type = 'general_law'"
    )
    op.execute(
        "COMMENT ON TABLE corpus.legal_proposition_subjects IS 'N:N proposition subjects. A proposition may concern multiple decisions, provisions, proceedings or documents of the same type.'"
    )


def _immutable_proposition_identity() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.reject_legal_proposition_identity_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.proposition_type IS DISTINCT FROM OLD.proposition_type
               OR NEW.canonical_text IS DISTINCT FROM OLD.canonical_text
               OR NEW.normalized_text IS DISTINCT FROM OLD.normalized_text
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION 'legal proposition identity is immutable; create a new proposition instead'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_propositions_immutable_identity BEFORE UPDATE ON corpus.legal_propositions FOR EACH ROW EXECUTE FUNCTION corpus.reject_legal_proposition_identity_mutation()"
    )
    op.execute(
        "COMMENT ON TABLE corpus.legal_propositions IS 'Immutable semantic claims. Verification/confidence may evolve, but changing proposition text/type/origin requires a new proposition identity.'"
    )


def _decision_multi_classification() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.decision_legal_matters (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            decision_id uuid NOT NULL,
            legal_matter_concept_id uuid NOT NULL REFERENCES corpus.legal_matter_concepts(id),
            relation_type text NOT NULL DEFAULT 'addresses',
            ordinal integer,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_legal_matters_relation_check CHECK (relation_type IN ('primary', 'addresses', 'incidental', 'background', 'other')),
            CONSTRAINT decision_legal_matters_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT decision_legal_matters_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT decision_legal_matters_same_scope_decision_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT decision_legal_matters_unique UNIQUE (decision_id, legal_matter_concept_id, relation_type)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE corpus.decision_procedures (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            decision_id uuid NOT NULL,
            procedure_concept_id uuid NOT NULL REFERENCES corpus.procedure_concepts(id),
            relation_type text NOT NULL DEFAULT 'uses',
            ordinal integer,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_procedures_relation_check CHECK (relation_type IN ('primary', 'uses', 'reviews', 'incident', 'other')),
            CONSTRAINT decision_procedures_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT decision_procedures_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT decision_procedures_same_scope_decision_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT decision_procedures_unique UNIQUE (decision_id, procedure_concept_id, relation_type)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_decisions.legal_matter_concept_id IS 'Legacy/preferred single classification only. Canonical multi-valued classification lives in decision_legal_matters.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_decisions.procedure_concept_id IS 'Legacy/preferred single classification only. Canonical multi-valued classification lives in decision_procedures.'"
    )


def _controversy_and_proceeding_cardinality() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.controversy_proceedings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            controversy_id uuid NOT NULL,
            proceeding_id uuid NOT NULL,
            relation_type text NOT NULL DEFAULT 'related',
            valid_from date,
            valid_to date,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT controversy_proceedings_relation_check CHECK (relation_type IN ('originating','appeal','cassation','constitutional_review','enforcement','incident','consolidated','severed','related','other')),
            CONSTRAINT controversy_proceedings_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT controversy_proceedings_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT controversy_proceedings_same_scope_controversy_fkey FOREIGN KEY (scope_id, controversy_id) REFERENCES corpus.legal_controversies(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT controversy_proceedings_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT controversy_proceedings_unique UNIQUE NULLS NOT DISTINCT (controversy_id, proceeding_id, relation_type, valid_from)
        )
        """
    )
    op.execute("DROP INDEX IF EXISTS corpus.proceeding_decisions_one_primary_per_case_idx")
    op.execute(
        "COMMENT ON COLUMN corpus.proceeding_decisions.is_primary IS 'Source/display preference only; no longer a legal identity invariant. A decision may belong equally to multiple consolidated proceedings.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.legal_proceedings.controversy_id IS 'Legacy/preferred grouping only. Canonical N:N litigation-family membership lives in controversy_proceedings.'"
    )


def _opinion_authorship_and_vote_stances() -> None:
    op.execute("ALTER TABLE corpus.judicial_opinions DROP CONSTRAINT IF EXISTS judicial_opinions_author_shape_check")
    op.execute(
        f"""
        CREATE TABLE corpus.judicial_opinion_authors (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            opinion_id uuid NOT NULL,
            case_id uuid NOT NULL,
            officer_id uuid NOT NULL,
            authorship_role text NOT NULL DEFAULT 'author',
            ordinal integer,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_opinion_authors_role_check CHECK (authorship_role IN ('author','coauthor','ponente','redactor','signatory','legacy_primary_author','other')),
            CONSTRAINT judicial_opinion_authors_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT judicial_opinion_authors_same_opinion_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id) ON DELETE CASCADE,
            CONSTRAINT judicial_opinion_authors_panel_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id),
            CONSTRAINT judicial_opinion_authors_unique UNIQUE (opinion_id, officer_id, authorship_role)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_opinion_authors (scope_id, opinion_id, case_id, officer_id, authorship_role, ordinal)
        SELECT scope_id, id, case_id, author_officer_id, 'legacy_primary_author', 1
        FROM corpus.judicial_opinions WHERE author_officer_id IS NOT NULL
        """
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_opinions.author_officer_id IS 'Deprecated single-author convenience field. Canonical authorship is N:N in judicial_opinion_authors.'"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.judicial_vote_stances (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            vote_id uuid NOT NULL REFERENCES corpus.decision_votes(id) ON DELETE CASCADE,
            case_id uuid NOT NULL,
            officer_id uuid NOT NULL,
            stance_type text NOT NULL,
            scope_type text NOT NULL,
            opinion_id uuid,
            proposition_id uuid,
            disposition_id uuid REFERENCES corpus.judicial_decision_dispositions(id) ON DELETE CASCADE,
            raw_stance text,
            note text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_vote_stances_type_check CHECK (stance_type IN ('joins','concurs','concurs_in_result','concurs_in_part','dissents','dissents_in_part','saved_vote','reservation','abstains','other')),
            CONSTRAINT judicial_vote_stances_scope_type_check CHECK (scope_type IN ('whole_decision','opinion','proposition','disposition')),
            CONSTRAINT judicial_vote_stances_shape_check CHECK ((scope_type = 'whole_decision' AND opinion_id IS NULL AND proposition_id IS NULL AND disposition_id IS NULL) OR (scope_type = 'opinion' AND opinion_id IS NOT NULL AND proposition_id IS NULL AND disposition_id IS NULL) OR (scope_type = 'proposition' AND opinion_id IS NULL AND proposition_id IS NOT NULL AND disposition_id IS NULL) OR (scope_type = 'disposition' AND opinion_id IS NULL AND proposition_id IS NULL AND disposition_id IS NOT NULL)),
            CONSTRAINT judicial_vote_stances_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT judicial_vote_stances_vote_member_fkey FOREIGN KEY (case_id, officer_id) REFERENCES corpus.decision_panel_members(case_id, officer_id),
            CONSTRAINT judicial_vote_stances_opinion_fkey FOREIGN KEY (scope_id, case_id, opinion_id) REFERENCES corpus.judicial_opinions(scope_id, case_id, id),
            CONSTRAINT judicial_vote_stances_proposition_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT judicial_vote_stances_unique UNIQUE NULLS NOT DISTINCT (vote_id, stance_type, scope_type, opinion_id, proposition_id, disposition_id)
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN corpus.decision_votes.vote_type IS 'Legacy/coarse whole-decision summary. Canonical partial or mixed judicial positions live in judicial_vote_stances.'"
    )


def _legal_entity_identity() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.legal_entities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid REFERENCES corpus.scopes(id),
            entity_kind text NOT NULL,
            canonical_name text NOT NULL,
            normalized_name text,
            country_code character(2),
            identity_status text NOT NULL DEFAULT 'identity_unresolved',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_entities_kind_check CHECK (entity_kind IN ('person','organization','court','public_body','international_body','other')),
            CONSTRAINT legal_entities_name_nonempty CHECK (btrim(canonical_name) <> ''),
            CONSTRAINT legal_entities_country_check CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{{2}}$'),
            CONSTRAINT legal_entities_identity_status_check CHECK (identity_status IN ('canonical','probable_duplicate','identity_unresolved','merged_with_canonical')),
            CONSTRAINT legal_entities_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute("ALTER TABLE corpus.participants ADD COLUMN legal_entity_id uuid REFERENCES corpus.legal_entities(id)")
    op.execute("ALTER TABLE corpus.judicial_officers ADD COLUMN legal_entity_id uuid REFERENCES corpus.legal_entities(id)")
    op.execute("ALTER TABLE corpus.courts ADD COLUMN legal_entity_id uuid REFERENCES corpus.legal_entities(id)")
    op.execute("ALTER TABLE corpus.legal_authorities ADD COLUMN legal_entity_id uuid REFERENCES corpus.legal_entities(id)")
    op.execute(
        """
        CREATE FUNCTION corpus.ensure_participant_legal_entity() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE k text;
        BEGIN
            IF NEW.legal_entity_id IS NULL THEN
                k := CASE NEW.participant_kind WHEN 'person' THEN 'person' WHEN 'organization' THEN 'organization' WHEN 'public_body' THEN 'public_body' ELSE 'other' END;
                INSERT INTO corpus.legal_entities (scope_id, entity_kind, canonical_name, normalized_name, identity_status)
                VALUES (NEW.scope_id, k, NEW.display_name, NEW.normalized_name, NEW.identity_status)
                RETURNING id INTO NEW.legal_entity_id;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute("CREATE TRIGGER participants_ensure_legal_entity BEFORE INSERT ON corpus.participants FOR EACH ROW EXECUTE FUNCTION corpus.ensure_participant_legal_entity()")
    op.execute(
        """
        CREATE FUNCTION corpus.ensure_officer_legal_entity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.legal_entity_id IS NULL THEN
                INSERT INTO corpus.legal_entities (scope_id, entity_kind, canonical_name, normalized_name, identity_status)
                VALUES (NEW.scope_id, 'person', NEW.display_name, NEW.normalized_name, NEW.identity_status)
                RETURNING id INTO NEW.legal_entity_id;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute("CREATE TRIGGER judicial_officers_ensure_legal_entity BEFORE INSERT ON corpus.judicial_officers FOR EACH ROW EXECUTE FUNCTION corpus.ensure_officer_legal_entity()")
    op.execute(
        f"""
        CREATE FUNCTION corpus.ensure_court_legal_entity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.legal_entity_id IS NULL THEN
                INSERT INTO corpus.legal_entities (scope_id, entity_kind, canonical_name, country_code, identity_status)
                VALUES ('{PUBLIC_SCOPE_ID}'::uuid, 'court', NEW.name, NEW.country_code, 'canonical')
                RETURNING id INTO NEW.legal_entity_id;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute("CREATE TRIGGER courts_ensure_legal_entity BEFORE INSERT ON corpus.courts FOR EACH ROW EXECUTE FUNCTION corpus.ensure_court_legal_entity()")
    op.execute(
        """
        CREATE FUNCTION corpus.ensure_authority_legal_entity() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE k text;
        BEGIN
            IF NEW.legal_entity_id IS NULL THEN
                k := CASE WHEN NEW.authority_type = 'court' THEN 'court' WHEN NEW.authority_type = 'international_body' THEN 'international_body' ELSE 'public_body' END;
                INSERT INTO corpus.legal_entities (scope_id, entity_kind, canonical_name, normalized_name, country_code, identity_status)
                VALUES (NEW.scope_id, k, NEW.canonical_name, NEW.normalized_name, NEW.country_code, NEW.identity_status)
                RETURNING id INTO NEW.legal_entity_id;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute("CREATE TRIGGER legal_authorities_ensure_legal_entity BEFORE INSERT ON corpus.legal_authorities FOR EACH ROW EXECUTE FUNCTION corpus.ensure_authority_legal_entity()")
    op.execute("CREATE INDEX participants_legal_entity_idx ON corpus.participants (legal_entity_id) WHERE legal_entity_id IS NOT NULL")
    op.execute("CREATE INDEX judicial_officers_legal_entity_idx ON corpus.judicial_officers (legal_entity_id) WHERE legal_entity_id IS NOT NULL")
    op.execute("CREATE INDEX courts_legal_entity_idx ON corpus.courts (legal_entity_id) WHERE legal_entity_id IS NOT NULL")
    op.execute("CREATE INDEX legal_authorities_legal_entity_idx ON corpus.legal_authorities (legal_entity_id) WHERE legal_entity_id IS NOT NULL")


def _claims_and_disposition_effects() -> None:
    op.execute(
        """
        CREATE TABLE corpus.legal_claim_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.legal_claim_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_claim_concepts_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT legal_claim_concepts_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT legal_claim_concepts_not_self_parent CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.legal_claim_concepts (code, name) VALUES
        ('principal_claim','Principal claim'), ('alternative_claim','Alternative/subsidiary claim'),
        ('counterclaim','Counterclaim'), ('procedural_exception','Procedural exception'),
        ('inadmissibility_motion','Inadmissibility motion'), ('appeal_ground','Appeal/cassation/review ground'),
        ('interim_request','Interim request'), ('other','Other')
        """
    )
    op.execute(
        f"""
        CREATE TABLE corpus.legal_claims (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proceeding_id uuid NOT NULL,
            asserted_by_party_role_id uuid,
            parent_claim_id uuid REFERENCES corpus.legal_claims(id),
            claim_concept_id uuid NOT NULL REFERENCES corpus.legal_claim_concepts(id),
            claim_text text NOT NULL,
            introduced_on date,
            ordinal integer,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_claims_text_check CHECK (btrim(claim_text) <> ''),
            CONSTRAINT legal_claims_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT legal_claims_parent_check CHECK (parent_claim_id IS NULL OR parent_claim_id <> id),
            CONSTRAINT legal_claims_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT legal_claims_same_scope_proceeding_fkey FOREIGN KEY (scope_id, proceeding_id) REFERENCES corpus.legal_proceedings(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT legal_claims_same_scope_party_role_fkey FOREIGN KEY (scope_id, asserted_by_party_role_id) REFERENCES corpus.proceeding_party_roles(scope_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.claim_effect_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            broader_concept_id uuid REFERENCES corpus.claim_effect_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT claim_effect_concepts_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT claim_effect_concepts_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT claim_effect_concepts_not_self_parent CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.claim_effect_concepts (code, name) VALUES
        ('granted','Granted'), ('partially_granted','Partially granted'), ('denied','Denied'),
        ('inadmissible','Inadmissible'), ('moot','Moot'), ('withdrawn','Withdrawn'), ('other','Other')
        """
    )
    op.execute(
        f"""
        CREATE TABLE corpus.disposition_claim_effects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            disposition_id uuid NOT NULL REFERENCES corpus.judicial_decision_dispositions(id) ON DELETE CASCADE,
            claim_id uuid NOT NULL REFERENCES corpus.legal_claims(id) ON DELETE CASCADE,
            effect_concept_id uuid NOT NULL REFERENCES corpus.claim_effect_concepts(id),
            note text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT disposition_claim_effects_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT disposition_claim_effects_unique UNIQUE (disposition_id, claim_id, effect_concept_id)
        )
        """
    )


def _norm_claim_identity() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.legal_norm_claims (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            proposition_id uuid NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            norm_kind text NOT NULL,
            legal_matter_concept_id uuid REFERENCES corpus.legal_matter_concepts(id),
            valid_from date,
            valid_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_norm_claims_kind_check CHECK (btrim(norm_kind) <> ''),
            CONSTRAINT legal_norm_claims_valid_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT legal_norm_claims_same_scope_prop_fkey FOREIGN KEY (scope_id, proposition_id) REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT legal_norm_claims_identity UNIQUE NULLS NOT DISTINCT (proposition_id, jurisdiction_code, norm_kind, legal_matter_concept_id, valid_from, valid_to),
            CONSTRAINT legal_norm_claims_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute("ALTER TABLE corpus.legal_norm_assertions ADD COLUMN norm_claim_id uuid")
    op.execute("DROP INDEX IF EXISTS corpus.legal_norm_assertions_current_idx")
    op.execute("ALTER TABLE corpus.legal_norm_assertions DROP CONSTRAINT IF EXISTS legal_norm_assertions_unique")
    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_norm_claim() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE c corpus.legal_norm_claims%ROWTYPE;
        BEGIN
            IF NEW.norm_claim_id IS NULL THEN
                INSERT INTO corpus.legal_norm_claims (
                    scope_id, proposition_id, jurisdiction_code, norm_kind, valid_from, valid_to
                ) VALUES (
                    NEW.scope_id, NEW.proposition_id, NEW.jurisdiction_code, NEW.norm_kind, NEW.valid_from, NEW.valid_to
                )
                ON CONFLICT (proposition_id, jurisdiction_code, norm_kind, legal_matter_concept_id, valid_from, valid_to) NULLS NOT DISTINCT
                DO UPDATE SET proposition_id = EXCLUDED.proposition_id
                RETURNING * INTO c;
                NEW.norm_claim_id := c.id;
            ELSE
                SELECT * INTO c FROM corpus.legal_norm_claims WHERE id = NEW.norm_claim_id;
                IF c.id IS NULL OR c.scope_id <> NEW.scope_id THEN
                    RAISE EXCEPTION 'unknown or cross-scope legal norm claim' USING ERRCODE = '23503';
                END IF;
                NEW.proposition_id := c.proposition_id;
                NEW.jurisdiction_code := c.jurisdiction_code;
                NEW.norm_kind := c.norm_kind;
                NEW.valid_from := c.valid_from;
                NEW.valid_to := c.valid_to;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_norm_assertions_canonical_claim BEFORE INSERT OR UPDATE OF norm_claim_id, proposition_id, jurisdiction_code, norm_kind, valid_from, valid_to ON corpus.legal_norm_assertions FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_norm_claim()"
    )
    op.execute(
        "ALTER TABLE corpus.legal_norm_assertions ADD CONSTRAINT legal_norm_assertions_claim_fkey FOREIGN KEY (scope_id, norm_claim_id) REFERENCES corpus.legal_norm_claims(scope_id, id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_norm_assertions_claim_history_key ON corpus.legal_norm_assertions (norm_claim_id, known_from)"
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_norm_assertions_current_idx ON corpus.legal_norm_assertions (norm_claim_id) WHERE known_to IS NULL"
    )
    op.execute(
        "COMMENT ON TABLE corpus.legal_norm_claims IS 'Contextual legal-norm identity: what proposition is claimed as law, in what jurisdiction/matter and legal-validity interval. Assertion rows are epistemic history about this claim.'"
    )


def _decision_legal_states() -> None:
    op.execute(
        """
        CREATE TABLE corpus.decision_state_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            broader_concept_id uuid REFERENCES corpus.decision_state_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_state_concepts_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT decision_state_concepts_name_check CHECK (btrim(name) <> ''),
            CONSTRAINT decision_state_concepts_not_self_parent CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.decision_state_concepts (code, name) VALUES
        ('appealable','Appealable'), ('final','Final'), ('res_judicata','Res judicata'),
        ('stayed','Stayed'), ('suspended','Suspended'), ('vacated','Vacated'),
        ('annulled','Annulled'), ('reversed','Reversed'), ('partially_reversed','Partially reversed'),
        ('enforceable','Enforceable'), ('superseded','Superseded'), ('other','Other')
        """
    )
    op.execute(
        f"""
        CREATE TABLE corpus.decision_legal_states (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            decision_id uuid NOT NULL,
            state_concept_id uuid NOT NULL REFERENCES corpus.decision_state_concepts(id),
            valid_from date,
            valid_to date,
            known_from timestamptz NOT NULL DEFAULT now(),
            known_to timestamptz,
            source_document_id uuid,
            evidence_case_page_id uuid,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT decision_legal_states_valid_range_check CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CONSTRAINT decision_legal_states_known_range_check CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT decision_legal_states_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT decision_legal_states_same_scope_decision_fkey FOREIGN KEY (scope_id, decision_id) REFERENCES corpus.judicial_decisions(scope_id, id) ON DELETE CASCADE,
            CONSTRAINT decision_legal_states_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT decision_legal_states_same_case_page_fkey FOREIGN KEY (decision_id, evidence_case_page_id) REFERENCES corpus.case_pages(case_id, id),
            CONSTRAINT decision_legal_states_history_key UNIQUE (decision_id, state_concept_id, known_from)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX decision_legal_states_current_idx ON corpus.decision_legal_states (decision_id, state_concept_id) WHERE known_to IS NULL"
    )
    op.execute(
        "COMMENT ON TABLE corpus.decision_legal_states IS 'Durative legal effect/state of a decision. Point-in-time acts remain in decision_legal_status_events; new state-like facts belong here.'"
    )
    op.execute(
        "COMMENT ON TABLE corpus.decision_legal_status_events IS 'Point-in-time legal lifecycle events. Legacy state-like event types remain readable for compatibility; new durative state facts belong in decision_legal_states.'"
    )


def downgrade() -> None:
    raise RuntimeError("0031 is an intentional pre-ingestion legal-reality normalization boundary")
