"""Generalize judicial semantics and disposition targets.

Revision ID: 0035_extensible_judicial_semantics
Revises: 0034_legal_reality_conformance
Create Date: 2026-09-16

Canonical opinion types, judicial stances and judicial-authority effects are
extensible concept identities rather than closed text enums. Judicial
judgments also gain one typed disposition-target relation that can point to
claims, procedural parties, proceedings, decisions or propositions.
"""

from alembic import op

revision = "0035_extensible_judicial_semantics"
down_revision = "0034_legal_reality_conformance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _generalize_opinion_types()
    _generalize_judicial_stances()
    _generalize_judicial_authority()
    _generalize_disposition_targets()


def _drop_check_constraints_containing(table: str, token: str) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid='corpus.{table}'::regclass
                  AND contype='c'
                  AND pg_get_constraintdef(oid) LIKE '%{token}%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE corpus.{table} DROP CONSTRAINT %I', r.conname
                );
            END LOOP;
        END $$
        """
    )


def _generalize_opinion_types() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_opinion_type_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.judicial_opinion_type_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CHECK (btrim(name) <> ''),
            CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_opinion_type_concepts (code,name) VALUES
        ('majority','Majority opinion'),
        ('plurality','Plurality opinion'),
        ('per_curiam','Per curiam / collective court opinion'),
        ('concurring','Concurring opinion'),
        ('dissenting','Dissenting opinion'),
        ('concurring_in_result','Opinion concurring in result'),
        ('separate','Separate opinion')
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinions "
        "ADD COLUMN opinion_type_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.judicial_opinions o
        SET opinion_type_concept_id=c.id
        FROM corpus.judicial_opinion_type_concepts c
        WHERE c.code=o.opinion_type
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinions "
        "ALTER COLUMN opinion_type_concept_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinions "
        "ADD CONSTRAINT judicial_opinions_type_concept_fkey "
        "FOREIGN KEY (opinion_type_concept_id) "
        "REFERENCES corpus.judicial_opinion_type_concepts(id)"
    )
    _drop_check_constraints_containing("judicial_opinions", "opinion_type")
    op.execute(
        """
        CREATE FUNCTION corpus.sync_judicial_opinion_type_concept()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        BEGIN
            IF NEW.opinion_type_concept_id IS NULL THEN
                SELECT id INTO NEW.opinion_type_concept_id
                FROM corpus.judicial_opinion_type_concepts
                WHERE code=NEW.opinion_type;
                IF NEW.opinion_type_concept_id IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial opinion type concept code: %',
                        NEW.opinion_type USING ERRCODE='23503';
                END IF;
            END IF;
            SELECT code INTO concept_code
            FROM corpus.judicial_opinion_type_concepts
            WHERE id=NEW.opinion_type_concept_id;
            IF concept_code IS NULL THEN
                RAISE EXCEPTION 'unknown judicial opinion type concept'
                    USING ERRCODE='23503';
            END IF;
            IF NEW.opinion_type IS NOT NULL AND NEW.opinion_type<>concept_code THEN
                RAISE EXCEPTION
                    'opinion_type conflicts with opinion_type_concept_id'
                    USING ERRCODE='23514';
            END IF;
            NEW.opinion_type := concept_code;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_opinions_sync_type_concept "
        "BEFORE INSERT OR UPDATE OF opinion_type,opinion_type_concept_id "
        "ON corpus.judicial_opinions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_judicial_opinion_type_concept()"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_opinions.opinion_type IS "
        "'Deprecated compatibility mirror; canonical identity is opinion_type_concept_id.'"
    )


def _generalize_judicial_stances() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_stance_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.judicial_stance_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CHECK (btrim(name) <> ''),
            CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_stance_concepts (code,name) VALUES
        ('joins','Joins'),
        ('concurs','Concurs'),
        ('concurs_in_result','Concurs in result'),
        ('concurs_in_part','Concurs in part'),
        ('dissents','Dissents'),
        ('dissents_in_part','Dissents in part'),
        ('saved_vote','Saved vote / voto salvado'),
        ('reservation','Reservation'),
        ('abstains','Abstains'),
        ('other','Other')
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances ADD COLUMN stance_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.judicial_vote_stances s
        SET stance_concept_id=c.id
        FROM corpus.judicial_stance_concepts c
        WHERE c.code=s.stance_type
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances "
        "ALTER COLUMN stance_concept_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances "
        "ADD CONSTRAINT judicial_vote_stances_concept_fkey "
        "FOREIGN KEY (stance_concept_id) REFERENCES corpus.judicial_stance_concepts(id)"
    )
    _drop_check_constraints_containing("judicial_vote_stances", "stance_type")
    op.execute(
        """
        CREATE FUNCTION corpus.sync_judicial_stance_concept()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        BEGIN
            IF NEW.stance_concept_id IS NULL THEN
                SELECT id INTO NEW.stance_concept_id
                FROM corpus.judicial_stance_concepts
                WHERE code=NEW.stance_type;
                IF NEW.stance_concept_id IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial stance concept code: %',
                        NEW.stance_type USING ERRCODE='23503';
                END IF;
            END IF;
            SELECT code INTO concept_code
            FROM corpus.judicial_stance_concepts
            WHERE id=NEW.stance_concept_id;
            IF concept_code IS NULL THEN
                RAISE EXCEPTION 'unknown judicial stance concept'
                    USING ERRCODE='23503';
            END IF;
            IF NEW.stance_type IS NOT NULL AND NEW.stance_type<>concept_code THEN
                RAISE EXCEPTION 'stance_type conflicts with stance_concept_id'
                    USING ERRCODE='23514';
            END IF;
            NEW.stance_type := concept_code;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_vote_stances_sync_concept "
        "BEFORE INSERT OR UPDATE OF stance_type,stance_concept_id "
        "ON corpus.judicial_vote_stances FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_judicial_stance_concept()"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_vote_stances.stance_type IS "
        "'Deprecated compatibility mirror; canonical identity is stance_concept_id.'"
    )


def _generalize_judicial_authority() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_authority_effect_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.judicial_authority_effect_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CHECK (btrim(name) <> ''),
            CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_authority_effect_concepts (code,name) VALUES
        ('binding','Binding authority'),
        ('persuasive','Persuasive authority'),
        ('nonbinding','Non-binding authority'),
        ('superseded','Superseded authority'),
        ('abrogated','Abrogated authority'),
        ('unknown','Unknown authority effect')
        """
    )
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "ADD COLUMN authority_effect_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.precedential_authority_assertions a
        SET authority_effect_concept_id=c.id
        FROM corpus.judicial_authority_effect_concepts c
        WHERE c.code=a.authority_type
        """
    )
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "ALTER COLUMN authority_effect_concept_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "ADD CONSTRAINT precedential_authority_effect_concept_fkey "
        "FOREIGN KEY (authority_effect_concept_id) "
        "REFERENCES corpus.judicial_authority_effect_concepts(id)"
    )
    _drop_check_constraints_containing(
        "precedential_authority_assertions", "authority_type"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS precedential_authority_no_knowledge_overlap "
        "ON corpus.precedential_authority_assertions"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.reject_precedent_knowledge_overlap()")
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "RENAME TO judicial_authority_assertions"
    )
    op.execute(
        "CREATE VIEW corpus.precedential_authority_assertions AS "
        "SELECT * FROM corpus.judicial_authority_assertions"
    )
    op.execute(
        "COMMENT ON VIEW corpus.precedential_authority_assertions IS "
        "'Deprecated compatibility name; canonical physical table is judicial_authority_assertions.'"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.sync_judicial_authority_effect_concept()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        BEGIN
            IF NEW.authority_effect_concept_id IS NULL THEN
                SELECT id INTO NEW.authority_effect_concept_id
                FROM corpus.judicial_authority_effect_concepts
                WHERE code=NEW.authority_type;
                IF NEW.authority_effect_concept_id IS NULL THEN
                    RAISE EXCEPTION
                        'unknown judicial authority effect concept code: %',
                        NEW.authority_type USING ERRCODE='23503';
                END IF;
            END IF;
            SELECT code INTO concept_code
            FROM corpus.judicial_authority_effect_concepts
            WHERE id=NEW.authority_effect_concept_id;
            IF concept_code IS NULL THEN
                RAISE EXCEPTION 'unknown judicial authority effect concept'
                    USING ERRCODE='23503';
            END IF;
            IF NEW.authority_type IS NOT NULL AND NEW.authority_type<>concept_code THEN
                RAISE EXCEPTION
                    'authority_type conflicts with authority_effect_concept_id'
                    USING ERRCODE='23514';
            END IF;
            NEW.authority_type := concept_code;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_authority_assertions_sync_effect_concept "
        "BEFORE INSERT OR UPDATE OF authority_type,authority_effect_concept_id "
        "ON corpus.judicial_authority_assertions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_judicial_authority_effect_concept()"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.reject_judicial_authority_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':',NEW.decision_id,NEW.proposition_id,
                    NEW.authority_effect_concept_id,NEW.jurisdiction_code,
                    NEW.court_id,NEW.legal_matter_concept_id),3501));
            IF EXISTS (
                SELECT 1 FROM corpus.judicial_authority_assertions k
                WHERE k.id<>NEW.id
                  AND k.decision_id=NEW.decision_id
                  AND k.proposition_id IS NOT DISTINCT FROM NEW.proposition_id
                  AND k.authority_effect_concept_id=NEW.authority_effect_concept_id
                  AND k.jurisdiction_code IS NOT DISTINCT FROM NEW.jurisdiction_code
                  AND k.court_id IS NOT DISTINCT FROM NEW.court_id
                  AND k.legal_matter_concept_id
                      IS NOT DISTINCT FROM NEW.legal_matter_concept_id
                  AND tstzrange(k.known_from,k.known_to,'[)')
                      && tstzrange(NEW.known_from,NEW.known_to,'[)')
            ) THEN
                RAISE EXCEPTION 'overlapping judicial-authority knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_authority_assertions_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.judicial_authority_assertions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "corpus.reject_judicial_authority_knowledge_overlap()"
    )
    op.execute(
        "COMMENT ON TABLE corpus.judicial_authority_assertions IS "
        "'Contextual judicial-authority assertion. Canonical effect vocabulary is extensible through judicial_authority_effect_concepts.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_authority_assertions.authority_type IS "
        "'Deprecated compatibility mirror; canonical identity is authority_effect_concept_id.'"
    )


def _generalize_disposition_targets() -> None:
    op.execute(
        "ALTER TABLE corpus.claim_effect_concepts "
        "RENAME TO disposition_effect_concepts"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "ADD COLUMN target_type text NOT NULL DEFAULT 'claim'"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts ADD COLUMN description text"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "ADD CONSTRAINT disposition_effect_concepts_target_type_check "
        "CHECK (target_type IN ('claim','party','proceeding','decision','proposition'))"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "ADD CONSTRAINT disposition_effect_concepts_target_id_key "
        "UNIQUE (target_type,id)"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "ADD CONSTRAINT disposition_effect_concepts_parent_same_target_fkey "
        "FOREIGN KEY (target_type,broader_concept_id) "
        "REFERENCES corpus.disposition_effect_concepts(target_type,id)"
    )
    op.execute(
        """
        INSERT INTO corpus.disposition_effect_concepts (target_type,code,name) VALUES
        ('party','orders','Orders party'),
        ('party','restrains','Restrains party'),
        ('party','awards_costs_against','Awards costs against party'),
        ('proceeding','remands','Remands proceeding'),
        ('proceeding','terminates','Terminates proceeding'),
        ('proceeding','stays','Stays proceeding'),
        ('decision','affirms','Affirms decision'),
        ('decision','reverses','Reverses decision'),
        ('decision','vacates','Vacates decision'),
        ('decision','annuls','Annuls decision'),
        ('decision','modifies','Modifies decision'),
        ('decision','cassates','Cassates decision'),
        ('proposition','adopts','Adopts proposition'),
        ('proposition','rejects','Rejects proposition'),
        ('proposition','limits','Limits proposition')
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS disposition_claim_effects_validate_membership "
        "ON corpus.disposition_claim_effects"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS corpus.validate_disposition_claim_membership()"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_claim_effects RENAME TO disposition_targets"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "RENAME COLUMN claim_id TO target_claim_id"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ALTER COLUMN target_claim_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD COLUMN target_type text NOT NULL DEFAULT 'claim'"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD COLUMN target_party_role_id uuid REFERENCES corpus.proceeding_party_roles(id)"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD COLUMN target_proceeding_id uuid REFERENCES corpus.legal_proceedings(id)"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD COLUMN target_decision_id uuid REFERENCES corpus.judicial_decisions(id)"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD COLUMN target_proposition_id uuid REFERENCES corpus.legal_propositions(id)"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD CONSTRAINT disposition_targets_target_type_check "
        "CHECK (target_type IN ('claim','party','proceeding','decision','proposition'))"
    )
    op.execute(
        """
        ALTER TABLE corpus.disposition_targets
        ADD CONSTRAINT disposition_targets_shape_check CHECK (
            (target_type='claim' AND target_claim_id IS NOT NULL
                AND target_party_role_id IS NULL AND target_proceeding_id IS NULL
                AND target_decision_id IS NULL AND target_proposition_id IS NULL)
            OR
            (target_type='party' AND target_claim_id IS NULL
                AND target_party_role_id IS NOT NULL AND target_proceeding_id IS NULL
                AND target_decision_id IS NULL AND target_proposition_id IS NULL)
            OR
            (target_type='proceeding' AND target_claim_id IS NULL
                AND target_party_role_id IS NULL AND target_proceeding_id IS NOT NULL
                AND target_decision_id IS NULL AND target_proposition_id IS NULL)
            OR
            (target_type='decision' AND target_claim_id IS NULL
                AND target_party_role_id IS NULL AND target_proceeding_id IS NULL
                AND target_decision_id IS NOT NULL AND target_proposition_id IS NULL)
            OR
            (target_type='proposition' AND target_claim_id IS NULL
                AND target_party_role_id IS NULL AND target_proceeding_id IS NULL
                AND target_decision_id IS NULL AND target_proposition_id IS NOT NULL)
        )
        """
    )
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "ADD CONSTRAINT disposition_targets_effect_target_fkey "
        "FOREIGN KEY (target_type,effect_concept_id) "
        "REFERENCES corpus.disposition_effect_concepts(target_type,id)"
    )
    for target_type, column in (
        ("claim", "target_claim_id"),
        ("party", "target_party_role_id"),
        ("proceeding", "target_proceeding_id"),
        ("decision", "target_decision_id"),
        ("proposition", "target_proposition_id"),
    ):
        op.execute(
            f"CREATE UNIQUE INDEX disposition_targets_{target_type}_key "
            f"ON corpus.disposition_targets(disposition_id,{column},effect_concept_id) "
            f"WHERE target_type='{target_type}'"
        )

    op.execute(
        """
        CREATE FUNCTION corpus.validate_disposition_target() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE source_decision uuid;
        DECLARE source_scope uuid;
        DECLARE target_scope uuid;
        DECLARE target_proceeding uuid;
        BEGIN
            SELECT case_id,scope_id INTO source_decision,source_scope
            FROM corpus.judicial_decision_dispositions
            WHERE id=NEW.disposition_id;
            IF source_decision IS NULL THEN
                RAISE EXCEPTION 'unknown judicial disposition' USING ERRCODE='23503';
            END IF;
            IF source_scope<>NEW.scope_id THEN
                RAISE EXCEPTION 'disposition target crosses corpus scope'
                    USING ERRCODE='23514';
            END IF;

            IF NEW.target_type='claim' THEN
                SELECT scope_id,proceeding_id INTO target_scope,target_proceeding
                FROM corpus.legal_claims WHERE id=NEW.target_claim_id;
                IF target_scope IS DISTINCT FROM NEW.scope_id THEN
                    RAISE EXCEPTION 'claim target crosses corpus scope'
                        USING ERRCODE='23514';
                END IF;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition cannot resolve a claim from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.target_type='party' THEN
                SELECT scope_id,proceeding_id INTO target_scope,target_proceeding
                FROM corpus.proceeding_party_roles WHERE id=NEW.target_party_role_id;
                IF target_scope IS DISTINCT FROM NEW.scope_id THEN
                    RAISE EXCEPTION 'party target crosses corpus scope'
                        USING ERRCODE='23514';
                END IF;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition cannot target a party from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.target_type='proceeding' THEN
                SELECT scope_id INTO target_scope
                FROM corpus.legal_proceedings WHERE id=NEW.target_proceeding_id;
                IF target_scope IS DISTINCT FROM NEW.scope_id THEN
                    RAISE EXCEPTION 'proceeding target crosses corpus scope'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.target_type='decision' THEN
                SELECT scope_id INTO target_scope
                FROM corpus.judicial_decisions WHERE id=NEW.target_decision_id;
                IF target_scope IS DISTINCT FROM NEW.scope_id THEN
                    RAISE EXCEPTION 'decision target crosses corpus scope'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.target_type='proposition' THEN
                SELECT scope_id INTO target_scope
                FROM corpus.legal_propositions WHERE id=NEW.target_proposition_id;
                IF target_scope IS DISTINCT FROM NEW.scope_id THEN
                    RAISE EXCEPTION 'proposition target crosses corpus scope'
                        USING ERRCODE='23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                ) AND NOT EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                      AND s.judicial_decision_id=source_decision
                ) THEN
                    RAISE EXCEPTION
                        'disposition proposition target belongs to another decision'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER disposition_targets_validate_target "
        "BEFORE INSERT OR UPDATE ON corpus.disposition_targets FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_disposition_target()"
    )
    op.execute(
        "COMMENT ON TABLE corpus.disposition_targets IS "
        "'Canonical typed targets of a judicial dispositive act: claim, procedural party role, proceeding, decision or proposition.'"
    )

    op.execute(
        """
        CREATE VIEW corpus.claim_effect_concepts AS
        SELECT id,code,name,broader_concept_id,created_at
        FROM corpus.disposition_effect_concepts
        WHERE target_type='claim'
        """
    )
    op.execute(
        "COMMENT ON VIEW corpus.claim_effect_concepts IS "
        "'Deprecated claim-only compatibility view; canonical concepts are disposition_effect_concepts.'"
    )
    op.execute(
        """
        CREATE VIEW corpus.disposition_claim_effects AS
        SELECT id,scope_id,disposition_id,target_claim_id AS claim_id,
               effect_concept_id,note,verification_status,verification_method,created_at
        FROM corpus.disposition_targets
        WHERE target_type='claim'
        """
    )
    op.execute(
        "COMMENT ON VIEW corpus.disposition_claim_effects IS "
        "'Deprecated claim-only compatibility view; canonical relation is disposition_targets.'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0035 is part of the intentional pre-ingestion legal-reality normalization boundary"
    )
