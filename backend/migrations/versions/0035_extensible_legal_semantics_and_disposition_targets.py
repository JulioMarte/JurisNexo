"""Normalize extensible judicial semantics and disposition targets.

Revision ID: 0035_extensible_legal_semantics
Revises: 0034_legal_reality_conformance
Create Date: 2026-09-16

This migration removes the remaining closed common-law-leaning vocabularies from
canonical judicial semantics and makes dispositive targets first-class N:N
relations. Compatibility text fields remain deterministic mirrors only.
"""

from alembic import op

revision = "0035_extensible_legal_semantics"
down_revision = "0034_legal_reality_conformance"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
STATUS = "'candidate','verified','conflicting','rejected','superseded'"


def upgrade() -> None:
    _extensible_opinion_types()
    _extensible_judicial_stances()
    _extensible_authority_effects()
    _generalize_disposition_targets()


def _extensible_opinion_types() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_opinion_type_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL,
            name text NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_opinion_type_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT judicial_opinion_type_concepts_name_check
                CHECK (btrim(name) <> ''),
            CONSTRAINT judicial_opinion_type_concepts_identity
                UNIQUE NULLS NOT DISTINCT (code, jurisdiction_code)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_opinion_type_concepts (code, name) VALUES
        ('majority', 'Majority opinion'),
        ('plurality', 'Plurality opinion'),
        ('per_curiam', 'Per curiam / institutional opinion'),
        ('concurring', 'Concurring opinion'),
        ('dissenting', 'Dissenting opinion'),
        ('concurring_in_result', 'Concurring in result'),
        ('separate', 'Separate opinion')
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinions "
        "ADD COLUMN opinion_type_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.judicial_opinions o
        SET opinion_type_concept_id = c.id
        FROM corpus.judicial_opinion_type_concepts c
        WHERE c.code = o.opinion_type AND c.jurisdiction_code IS NULL
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
    op.execute(
        "ALTER TABLE corpus.judicial_opinions "
        "DROP CONSTRAINT judicial_opinions_type_check"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_judicial_opinion_type() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE concept_id uuid;
        DECLARE concept_code text;
        BEGIN
            IF NEW.opinion_type_concept_id IS NULL THEN
                SELECT id, code INTO concept_id, concept_code
                FROM corpus.judicial_opinion_type_concepts
                WHERE code = NEW.opinion_type AND jurisdiction_code IS NULL;
                IF concept_id IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial opinion type concept'
                        USING ERRCODE = '23503';
                END IF;
                NEW.opinion_type_concept_id := concept_id;
            ELSE
                SELECT code INTO concept_code
                FROM corpus.judicial_opinion_type_concepts
                WHERE id = NEW.opinion_type_concept_id;
                IF concept_code IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial opinion type concept'
                        USING ERRCODE = '23503';
                END IF;
                IF NEW.opinion_type IS NOT NULL
                   AND NEW.opinion_type IS DISTINCT FROM concept_code THEN
                    RAISE EXCEPTION 'opinion type text disagrees with canonical concept'
                        USING ERRCODE = '23514';
                END IF;
                NEW.opinion_type := concept_code;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_opinions_canonical_type "
        "BEFORE INSERT OR UPDATE OF opinion_type, opinion_type_concept_id "
        "ON corpus.judicial_opinions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.canonicalize_judicial_opinion_type()"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_opinions.opinion_type IS "
        "'Compatibility code mirrored from opinion_type_concept_id; canonical semantics use judicial_opinion_type_concepts.'"
    )


def _extensible_judicial_stances() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_stance_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL,
            name text NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_stance_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT judicial_stance_concepts_name_check
                CHECK (btrim(name) <> ''),
            CONSTRAINT judicial_stance_concepts_identity
                UNIQUE NULLS NOT DISTINCT (code, jurisdiction_code)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_stance_concepts (code, name) VALUES
        ('joins', 'Joins'),
        ('concurs', 'Concurs'),
        ('concurs_in_result', 'Concurs in result'),
        ('concurs_in_part', 'Concurs in part'),
        ('dissents', 'Dissents'),
        ('dissents_in_part', 'Dissents in part'),
        ('saved_vote', 'Saved vote'),
        ('reservation', 'Reservation'),
        ('abstains', 'Abstains'),
        ('other', 'Other')
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances "
        "ADD COLUMN stance_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.judicial_vote_stances s
        SET stance_concept_id = c.id
        FROM corpus.judicial_stance_concepts c
        WHERE c.code = s.stance_type AND c.jurisdiction_code IS NULL
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
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances "
        "DROP CONSTRAINT judicial_vote_stances_stance_type_check"
    )
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'corpus.judicial_vote_stances'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) LIKE '%stance_type%';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE corpus.judicial_vote_stances DROP CONSTRAINT %I',
                    constraint_name
                );
            END IF;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances "
        "ADD CONSTRAINT judicial_vote_stances_canonical_unique "
        "UNIQUE NULLS NOT DISTINCT ("
        "vote_id, stance_concept_id, scope_type, opinion_id, proposition_id, disposition_id"
        ")"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_judicial_stance() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE concept_id uuid;
        DECLARE concept_code text;
        BEGIN
            IF NEW.stance_concept_id IS NULL THEN
                SELECT id, code INTO concept_id, concept_code
                FROM corpus.judicial_stance_concepts
                WHERE code = NEW.stance_type AND jurisdiction_code IS NULL;
                IF concept_id IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial stance concept'
                        USING ERRCODE = '23503';
                END IF;
                NEW.stance_concept_id := concept_id;
            ELSE
                SELECT code INTO concept_code
                FROM corpus.judicial_stance_concepts
                WHERE id = NEW.stance_concept_id;
                IF concept_code IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial stance concept'
                        USING ERRCODE = '23503';
                END IF;
                IF NEW.stance_type IS NOT NULL
                   AND NEW.stance_type IS DISTINCT FROM concept_code THEN
                    RAISE EXCEPTION 'stance text disagrees with canonical concept'
                        USING ERRCODE = '23514';
                END IF;
                NEW.stance_type := concept_code;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_vote_stances_canonical_stance "
        "BEFORE INSERT OR UPDATE OF stance_type, stance_concept_id "
        "ON corpus.judicial_vote_stances FOR EACH ROW "
        "EXECUTE FUNCTION corpus.canonicalize_judicial_stance()"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_vote_stances.stance_type IS "
        "'Compatibility code mirrored from stance_concept_id; canonical semantics use judicial_stance_concepts.'"
    )


def _extensible_authority_effects() -> None:
    op.execute(
        """
        CREATE TABLE corpus.judicial_authority_effect_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL,
            name text NOT NULL,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_authority_effect_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT judicial_authority_effect_concepts_name_check
                CHECK (btrim(name) <> ''),
            CONSTRAINT judicial_authority_effect_concepts_identity
                UNIQUE NULLS NOT DISTINCT (code, jurisdiction_code)
        )
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_authority_effect_concepts (code, name) VALUES
        ('binding', 'Binding'),
        ('persuasive', 'Persuasive'),
        ('nonbinding', 'Non-binding'),
        ('superseded', 'Superseded'),
        ('abrogated', 'Abrogated'),
        ('unknown', 'Unknown')
        """
    )
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "ADD COLUMN authority_effect_concept_id uuid"
    )
    op.execute(
        """
        UPDATE corpus.precedential_authority_assertions a
        SET authority_effect_concept_id = c.id
        FROM corpus.judicial_authority_effect_concepts c
        WHERE c.code = a.authority_type AND c.jurisdiction_code IS NULL
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
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "DROP CONSTRAINT precedential_authority_assertions_type_check"
    )
    op.execute("DROP INDEX corpus.precedential_authority_current_idx")
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "RENAME COLUMN authority_type TO authority_effect_code"
    )
    op.execute(
        "ALTER TABLE corpus.precedential_authority_assertions "
        "RENAME TO judicial_authority_effect_assertions"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_judicial_authority_effect() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE concept_id uuid;
        DECLARE concept_code text;
        BEGIN
            IF NEW.authority_effect_concept_id IS NULL THEN
                SELECT id, code INTO concept_id, concept_code
                FROM corpus.judicial_authority_effect_concepts
                WHERE code = NEW.authority_effect_code AND jurisdiction_code IS NULL;
                IF concept_id IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial authority effect concept'
                        USING ERRCODE = '23503';
                END IF;
                NEW.authority_effect_concept_id := concept_id;
            ELSE
                SELECT code INTO concept_code
                FROM corpus.judicial_authority_effect_concepts
                WHERE id = NEW.authority_effect_concept_id;
                IF concept_code IS NULL THEN
                    RAISE EXCEPTION 'unknown judicial authority effect concept'
                        USING ERRCODE = '23503';
                END IF;
                IF NEW.authority_effect_code IS NOT NULL
                   AND NEW.authority_effect_code IS DISTINCT FROM concept_code THEN
                    RAISE EXCEPTION 'authority effect text disagrees with canonical concept'
                        USING ERRCODE = '23514';
                END IF;
                NEW.authority_effect_code := concept_code;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_authority_effects_canonical_concept "
        "BEFORE INSERT OR UPDATE OF authority_effect_code, authority_effect_concept_id "
        "ON corpus.judicial_authority_effect_assertions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.canonicalize_judicial_authority_effect()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.reject_precedent_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.decision_id, NEW.proposition_id,
                    NEW.authority_effect_concept_id, NEW.jurisdiction_code,
                    NEW.court_id, NEW.legal_matter_concept_id),
                2804
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.judicial_authority_effect_assertions k
                WHERE k.id <> NEW.id
                  AND k.decision_id = NEW.decision_id
                  AND k.proposition_id IS NOT DISTINCT FROM NEW.proposition_id
                  AND k.authority_effect_concept_id = NEW.authority_effect_concept_id
                  AND k.jurisdiction_code IS NOT DISTINCT FROM NEW.jurisdiction_code
                  AND k.court_id IS NOT DISTINCT FROM NEW.court_id
                  AND k.legal_matter_concept_id IS NOT DISTINCT FROM NEW.legal_matter_concept_id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping judicial authority-effect knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX judicial_authority_effect_current_idx
        ON corpus.judicial_authority_effect_assertions (
            decision_id,
            coalesce(proposition_id, '00000000-0000-0000-0000-000000000000'::uuid),
            authority_effect_concept_id,
            coalesce(jurisdiction_code, ''),
            coalesce(court_id, '00000000-0000-0000-0000-000000000000'::uuid),
            coalesce(legal_matter_concept_id, '00000000-0000-0000-0000-000000000000'::uuid)
        ) WHERE known_to IS NULL
        """
    )
    op.execute(
        """
        CREATE VIEW corpus.precedential_authority_assertions AS
        SELECT
            id, scope_id, decision_id, proposition_id,
            authority_effect_code AS authority_type,
            jurisdiction_code, court_id, legal_matter_concept_id,
            valid_from, valid_to, basis, verification_status,
            verification_method, created_at, known_from, known_to,
            authority_effect_concept_id
        FROM corpus.judicial_authority_effect_assertions
        """
    )
    op.execute(
        "COMMENT ON TABLE corpus.judicial_authority_effect_assertions IS "
        "'Canonical contextual judicial-authority effects. Concepts are jurisdiction-extensible and are not assumed to form a universal common-law precedent hierarchy.'"
    )
    op.execute(
        "COMMENT ON VIEW corpus.precedential_authority_assertions IS "
        "'Deprecated compatibility view. Canonical persistence is judicial_authority_effect_assertions.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_authority_effect_assertions.authority_effect_code IS "
        "'Compatibility code mirrored from authority_effect_concept_id; canonical semantics use judicial_authority_effect_concepts.'"
    )


def _generalize_disposition_targets() -> None:
    op.execute(
        "ALTER TABLE corpus.judicial_decision_dispositions "
        "ADD CONSTRAINT judicial_decision_dispositions_scope_id_id_key "
        "UNIQUE (scope_id, id)"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.judicial_disposition_targets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            disposition_id uuid NOT NULL,
            target_type text NOT NULL,
            claim_id uuid,
            party_role_id uuid,
            proceeding_id uuid,
            judicial_decision_id uuid,
            proposition_id uuid,
            target_role text NOT NULL DEFAULT 'affected',
            raw_target_text text,
            source_claim_effect_id uuid REFERENCES corpus.disposition_claim_effects(id)
                ON DELETE CASCADE,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT judicial_disposition_targets_type_check CHECK (
                target_type IN (
                    'claim', 'party_role', 'proceeding',
                    'judicial_decision', 'proposition'
                )
            ),
            CONSTRAINT judicial_disposition_targets_shape_check CHECK (
                (target_type = 'claim'
                    AND claim_id IS NOT NULL
                    AND party_role_id IS NULL
                    AND proceeding_id IS NULL
                    AND judicial_decision_id IS NULL
                    AND proposition_id IS NULL)
                OR
                (target_type = 'party_role'
                    AND claim_id IS NULL
                    AND party_role_id IS NOT NULL
                    AND proceeding_id IS NULL
                    AND judicial_decision_id IS NULL
                    AND proposition_id IS NULL)
                OR
                (target_type = 'proceeding'
                    AND claim_id IS NULL
                    AND party_role_id IS NULL
                    AND proceeding_id IS NOT NULL
                    AND judicial_decision_id IS NULL
                    AND proposition_id IS NULL)
                OR
                (target_type = 'judicial_decision'
                    AND claim_id IS NULL
                    AND party_role_id IS NULL
                    AND proceeding_id IS NULL
                    AND judicial_decision_id IS NOT NULL
                    AND proposition_id IS NULL)
                OR
                (target_type = 'proposition'
                    AND claim_id IS NULL
                    AND party_role_id IS NULL
                    AND proceeding_id IS NULL
                    AND judicial_decision_id IS NULL
                    AND proposition_id IS NOT NULL)
            ),
            CONSTRAINT judicial_disposition_targets_role_check
                CHECK (btrim(target_role) <> ''),
            CONSTRAINT judicial_disposition_targets_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT judicial_disposition_targets_claim_effect_shape_check
                CHECK (source_claim_effect_id IS NULL OR target_type = 'claim'),
            CONSTRAINT judicial_disposition_targets_same_scope_disposition_fkey
                FOREIGN KEY (scope_id, disposition_id)
                REFERENCES corpus.judicial_decision_dispositions(scope_id, id)
                ON DELETE CASCADE,
            CONSTRAINT judicial_disposition_targets_same_scope_claim_fkey
                FOREIGN KEY (scope_id, claim_id)
                REFERENCES corpus.legal_claims(scope_id, id),
            CONSTRAINT judicial_disposition_targets_same_scope_party_role_fkey
                FOREIGN KEY (scope_id, party_role_id)
                REFERENCES corpus.proceeding_party_roles(scope_id, id),
            CONSTRAINT judicial_disposition_targets_same_scope_proceeding_fkey
                FOREIGN KEY (scope_id, proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id, id),
            CONSTRAINT judicial_disposition_targets_same_scope_decision_fkey
                FOREIGN KEY (scope_id, judicial_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id, id),
            CONSTRAINT judicial_disposition_targets_same_scope_proposition_fkey
                FOREIGN KEY (scope_id, proposition_id)
                REFERENCES corpus.legal_propositions(scope_id, id),
            CONSTRAINT judicial_disposition_targets_unique
                UNIQUE NULLS NOT DISTINCT (
                    disposition_id, target_type, claim_id, party_role_id,
                    proceeding_id, judicial_decision_id, proposition_id, target_role
                ),
            CONSTRAINT judicial_disposition_targets_claim_effect_unique
                UNIQUE NULLS NOT DISTINCT (source_claim_effect_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX judicial_disposition_targets_disposition_idx "
        "ON corpus.judicial_disposition_targets "
        "(scope_id, disposition_id, target_type, target_role)"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.validate_judicial_disposition_target() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE source_decision uuid;
        DECLARE target_proceeding uuid;
        DECLARE projected_disposition uuid;
        DECLARE projected_claim uuid;
        BEGIN
            SELECT case_id INTO source_decision
            FROM corpus.judicial_decision_dispositions
            WHERE id = NEW.disposition_id AND scope_id = NEW.scope_id;
            IF source_decision IS NULL THEN
                RAISE EXCEPTION 'unknown judicial disposition target source'
                    USING ERRCODE = '23503';
            END IF;

            IF NEW.target_type = 'claim' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.legal_claims
                WHERE id = NEW.claim_id AND scope_id = NEW.scope_id;
            ELSIF NEW.target_type = 'party_role' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.proceeding_party_roles
                WHERE id = NEW.party_role_id AND scope_id = NEW.scope_id;
            ELSIF NEW.target_type = 'proceeding' THEN
                target_proceeding := NEW.proceeding_id;
            END IF;

            IF target_proceeding IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM corpus.proceeding_decisions pd
                WHERE pd.scope_id = NEW.scope_id
                  AND pd.proceeding_id = target_proceeding
                  AND pd.case_id = source_decision
                  AND pd.verification_status NOT IN ('rejected', 'superseded')
            ) THEN
                RAISE EXCEPTION
                    'disposition target proceeding is unrelated to the source decision'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.target_type = 'proposition'
               AND EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id = NEW.scope_id
                      AND s.proposition_id = NEW.proposition_id
                      AND s.subject_type = 'judicial_decision'
               )
               AND NOT EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id = NEW.scope_id
                      AND s.proposition_id = NEW.proposition_id
                      AND s.subject_type = 'judicial_decision'
                      AND s.judicial_decision_id = source_decision
               ) THEN
                RAISE EXCEPTION
                    'disposition proposition target belongs only to another decision'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.source_claim_effect_id IS NOT NULL THEN
                SELECT disposition_id, claim_id
                INTO projected_disposition, projected_claim
                FROM corpus.disposition_claim_effects
                WHERE id = NEW.source_claim_effect_id;
                IF projected_disposition IS DISTINCT FROM NEW.disposition_id
                   OR projected_claim IS DISTINCT FROM NEW.claim_id THEN
                    RAISE EXCEPTION
                        'claim-effect projection does not match disposition target'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_disposition_targets_validate "
        "BEFORE INSERT OR UPDATE ON corpus.judicial_disposition_targets "
        "FOR EACH ROW EXECUTE FUNCTION corpus.validate_judicial_disposition_target()"
    )

    op.execute(
        """
        INSERT INTO corpus.judicial_disposition_targets (
            scope_id, disposition_id, target_type, judicial_decision_id,
            target_role, verification_status, verification_method
        )
        SELECT scope_id, id, 'judicial_decision', affected_case_id,
               'affected', verification_status, 'legacy_affected_field_backfill'
        FROM corpus.judicial_decision_dispositions
        WHERE affected_case_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_disposition_targets (
            scope_id, disposition_id, target_type, proceeding_id,
            target_role, verification_status, verification_method
        )
        SELECT scope_id, id, 'proceeding', affected_proceeding_id,
               'affected', verification_status, 'legacy_affected_field_backfill'
        FROM corpus.judicial_decision_dispositions
        WHERE affected_proceeding_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION corpus.sync_legacy_disposition_targets() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.affected_case_id IS DISTINCT FROM NEW.affected_case_id
               AND OLD.affected_case_id IS NOT NULL THEN
                DELETE FROM corpus.judicial_disposition_targets
                WHERE disposition_id = NEW.id
                  AND target_type = 'judicial_decision'
                  AND judicial_decision_id = OLD.affected_case_id
                  AND target_role = 'affected'
                  AND verification_method IN (
                      'legacy_affected_field', 'legacy_affected_field_backfill'
                  );
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.affected_proceeding_id IS DISTINCT FROM NEW.affected_proceeding_id
               AND OLD.affected_proceeding_id IS NOT NULL THEN
                DELETE FROM corpus.judicial_disposition_targets
                WHERE disposition_id = NEW.id
                  AND target_type = 'proceeding'
                  AND proceeding_id = OLD.affected_proceeding_id
                  AND target_role = 'affected'
                  AND verification_method IN (
                      'legacy_affected_field', 'legacy_affected_field_backfill'
                  );
            END IF;

            IF NEW.affected_case_id IS NOT NULL THEN
                INSERT INTO corpus.judicial_disposition_targets (
                    scope_id, disposition_id, target_type, judicial_decision_id,
                    target_role, verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.id, 'judicial_decision', NEW.affected_case_id,
                    'affected', NEW.verification_status, 'legacy_affected_field'
                ) ON CONFLICT DO NOTHING;
            END IF;
            IF NEW.affected_proceeding_id IS NOT NULL THEN
                INSERT INTO corpus.judicial_disposition_targets (
                    scope_id, disposition_id, target_type, proceeding_id,
                    target_role, verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.id, 'proceeding', NEW.affected_proceeding_id,
                    'affected', NEW.verification_status, 'legacy_affected_field'
                ) ON CONFLICT DO NOTHING;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_dispositions_sync_legacy_targets "
        "AFTER INSERT OR UPDATE OF affected_case_id, affected_proceeding_id "
        "ON corpus.judicial_decision_dispositions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_legacy_disposition_targets()"
    )

    op.execute(
        """
        CREATE FUNCTION corpus.sync_disposition_claim_effect_target() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE effect_scope uuid;
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.disposition_id IS DISTINCT FROM NEW.disposition_id
                    OR OLD.claim_id IS DISTINCT FROM NEW.claim_id) THEN
                DELETE FROM corpus.judicial_disposition_targets
                WHERE source_claim_effect_id = OLD.id;
            END IF;
            SELECT scope_id INTO effect_scope
            FROM corpus.legal_claims WHERE id = NEW.claim_id;
            INSERT INTO corpus.judicial_disposition_targets (
                scope_id, disposition_id, target_type, claim_id,
                target_role, source_claim_effect_id,
                verification_status, verification_method
            ) VALUES (
                effect_scope, NEW.disposition_id, 'claim', NEW.claim_id,
                'resolved_claim', NEW.id,
                NEW.verification_status, 'claim_effect_projection'
            )
            ON CONFLICT (source_claim_effect_id)
            DO UPDATE SET
                scope_id = EXCLUDED.scope_id,
                disposition_id = EXCLUDED.disposition_id,
                claim_id = EXCLUDED.claim_id,
                verification_status = EXCLUDED.verification_status;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER disposition_claim_effects_sync_target "
        "AFTER INSERT OR UPDATE OF disposition_id, claim_id, verification_status "
        "ON corpus.disposition_claim_effects FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_disposition_claim_effect_target()"
    )
    op.execute(
        """
        INSERT INTO corpus.judicial_disposition_targets (
            scope_id, disposition_id, target_type, claim_id,
            target_role, source_claim_effect_id,
            verification_status, verification_method
        )
        SELECT c.scope_id, e.disposition_id, 'claim', e.claim_id,
               'resolved_claim', e.id,
               e.verification_status, 'claim_effect_projection'
        FROM corpus.disposition_claim_effects e
        JOIN corpus.legal_claims c ON c.id = e.claim_id
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        "COMMENT ON TABLE corpus.judicial_disposition_targets IS "
        "'Canonical N:N target identities for dispositive clauses. One row targets exactly one claim, procedural party role, proceeding, judicial decision or proposition.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_decision_dispositions.affected_case_id IS "
        "'Legacy singular target convenience; canonical decision targets live in judicial_disposition_targets.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_decision_dispositions.affected_proceeding_id IS "
        "'Legacy singular target convenience; canonical proceeding targets live in judicial_disposition_targets.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.judicial_disposition_targets.party_role_id IS "
        "'Targets a party in its procedural capacity; underlying participant/legal-entity identity remains reachable through proceeding_party_roles.'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0035 is part of the intentional pre-ingestion legal-semantics normalization boundary"
    )
