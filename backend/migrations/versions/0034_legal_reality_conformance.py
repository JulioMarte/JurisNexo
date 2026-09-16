"""Close remaining Legal Reality V2 conformance gaps.

Revision ID: 0034_legal_reality_conformance
Revises: 0033_legal_reality_compat_sync
Create Date: 2026-09-16

This migration turns documented Legal Reality V2 semantics into database
invariants where 0031-0033 still allowed contradictory states.
"""

from alembic import op

revision = "0034_legal_reality_conformance"
down_revision = "0033_legal_reality_compat_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _replace_legacy_sync_functions()
    _bind_proposition_stances_to_decisions()
    _bind_claim_hierarchy_and_party_roles_to_proceedings()
    _separate_decision_events_from_states()


def _replace_legacy_sync_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.sync_legacy_decision_classification()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.legal_matter_concept_id IS DISTINCT FROM NEW.legal_matter_concept_id
               AND OLD.legal_matter_concept_id IS NOT NULL THEN
                DELETE FROM corpus.decision_legal_matters
                WHERE decision_id = NEW.id
                  AND legal_matter_concept_id = OLD.legal_matter_concept_id
                  AND relation_type = 'primary'
                  AND verification_method IN (
                      'legacy_compatibility_field',
                      'legacy_compatibility_backfill'
                  );
            END IF;
            IF NEW.legal_matter_concept_id IS NOT NULL THEN
                INSERT INTO corpus.decision_legal_matters (
                    scope_id, decision_id, legal_matter_concept_id,
                    relation_type, verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.id, NEW.legal_matter_concept_id,
                    'primary', 'candidate', 'legacy_compatibility_field'
                ) ON CONFLICT DO NOTHING;
            END IF;

            IF TG_OP = 'UPDATE'
               AND OLD.procedure_concept_id IS DISTINCT FROM NEW.procedure_concept_id
               AND OLD.procedure_concept_id IS NOT NULL THEN
                DELETE FROM corpus.decision_procedures
                WHERE decision_id = NEW.id
                  AND procedure_concept_id = OLD.procedure_concept_id
                  AND relation_type = 'primary'
                  AND verification_method IN (
                      'legacy_compatibility_field',
                      'legacy_compatibility_backfill'
                  );
            END IF;
            IF NEW.procedure_concept_id IS NOT NULL THEN
                INSERT INTO corpus.decision_procedures (
                    scope_id, decision_id, procedure_concept_id,
                    relation_type, verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.id, NEW.procedure_concept_id,
                    'primary', 'candidate', 'legacy_compatibility_field'
                ) ON CONFLICT DO NOTHING;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.sync_legacy_proceeding_controversy()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.controversy_id IS DISTINCT FROM NEW.controversy_id
               AND OLD.controversy_id IS NOT NULL THEN
                DELETE FROM corpus.controversy_proceedings
                WHERE proceeding_id = NEW.id
                  AND controversy_id = OLD.controversy_id
                  AND relation_type = 'related'
                  AND verification_method IN (
                      'legacy_compatibility_field',
                      'legacy_compatibility_backfill'
                  );
            END IF;
            IF NEW.controversy_id IS NOT NULL THEN
                INSERT INTO corpus.controversy_proceedings (
                    scope_id, controversy_id, proceeding_id, relation_type,
                    verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.controversy_id, NEW.id, 'related',
                    'candidate', 'legacy_compatibility_field'
                ) ON CONFLICT DO NOTHING;
            END IF;
            RETURN NEW;
        END $$
        """
    )


def _bind_proposition_stances_to_decisions() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.validate_vote_stance_target() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.scope_type = 'proposition' AND NOT EXISTS (
                SELECT 1
                FROM corpus.legal_proposition_subjects s
                WHERE s.proposition_id = NEW.proposition_id
                  AND s.scope_id = NEW.scope_id
                  AND s.subject_type = 'judicial_decision'
                  AND s.judicial_decision_id = NEW.case_id
            ) THEN
                RAISE EXCEPTION
                    'proposition-scoped judicial stance must target a proposition about the same decision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_vote_stances_validate_target "
        "BEFORE INSERT OR UPDATE OF scope_type, proposition_id, case_id, scope_id "
        "ON corpus.judicial_vote_stances FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_vote_stance_target()"
    )


def _bind_claim_hierarchy_and_party_roles_to_proceedings() -> None:
    op.execute(
        "ALTER TABLE corpus.legal_claims "
        "ADD CONSTRAINT legal_claims_scope_proceeding_id_key "
        "UNIQUE (scope_id, proceeding_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.proceeding_party_roles "
        "ADD CONSTRAINT proceeding_party_roles_scope_proceeding_id_key "
        "UNIQUE (scope_id, proceeding_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_claims "
        "ADD CONSTRAINT legal_claims_parent_same_proceeding_fkey "
        "FOREIGN KEY (scope_id, proceeding_id, parent_claim_id) "
        "REFERENCES corpus.legal_claims(scope_id, proceeding_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_claims "
        "ADD CONSTRAINT legal_claims_party_role_same_proceeding_fkey "
        "FOREIGN KEY (scope_id, proceeding_id, asserted_by_party_role_id) "
        "REFERENCES corpus.proceeding_party_roles(scope_id, proceeding_id, id)"
    )


def _separate_decision_events_from_states() -> None:
    op.execute(
        "ALTER TABLE corpus.decision_legal_status_events "
        "DROP CONSTRAINT decision_legal_status_events_type_check"
    )
    op.execute(
        "ALTER TABLE corpus.decision_legal_status_events "
        "ADD CONSTRAINT decision_legal_status_events_type_check "
        "CHECK (status_type IN ("
        "'issued','notified','vacated','annulled','reversed',"
        "'partially_reversed','enforced','superseded','other'"
        "))"
    )
    op.execute(
        "DELETE FROM corpus.decision_state_concepts "
        "WHERE code IN ('vacated','annulled','reversed','partially_reversed') "
        "AND NOT EXISTS ("
        "SELECT 1 FROM corpus.decision_legal_states s "
        "WHERE s.state_concept_id = decision_state_concepts.id"
        ")"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.validate_decision_state_concept() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        BEGIN
            SELECT code INTO concept_code
            FROM corpus.decision_state_concepts
            WHERE id = NEW.state_concept_id;
            IF concept_code IN (
                'vacated', 'annulled', 'reversed', 'partially_reversed'
            ) THEN
                RAISE EXCEPTION
                    'point-in-time judicial acts cannot be persisted as decision legal states'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER decision_legal_states_validate_concept "
        "BEFORE INSERT OR UPDATE OF state_concept_id "
        "ON corpus.decision_legal_states FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_decision_state_concept()"
    )
    op.execute(
        "COMMENT ON TABLE corpus.decision_legal_status_events IS "
        "'Point-in-time lifecycle acts only. New state-like facts such as finality, res judicata, appealability, stays and suspension belong in decision_legal_states.'"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0034 is part of the intentional pre-ingestion legal-reality normalization boundary"
    )
