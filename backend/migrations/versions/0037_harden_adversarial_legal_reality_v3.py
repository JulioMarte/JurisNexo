"""Harden Adversarial Legal Reality V3.

Revision ID: 0037_harden_legal_reality_v3
Revises: 0036_legal_reality_v3
Create Date: 2026-09-16
"""

from alembic import op

revision = "0037_harden_legal_reality_v3"
down_revision = "0036_legal_reality_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION corpus.default_adjudicative_act_type() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT id FROM corpus.adjudicative_act_type_concepts WHERE code='decision'
        $$
    """)
    op.execute("ALTER TABLE corpus.judicial_decisions ALTER COLUMN act_type_concept_id SET DEFAULT corpus.default_adjudicative_act_type()")
    op.execute("COMMENT ON FUNCTION corpus.default_adjudicative_act_type() IS 'Compatibility default only. Extraction should set the observed juridical act type whenever known.'")

    op.execute("""
        CREATE FUNCTION corpus.validate_proceeding_relation_symmetry() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE symmetric_relation boolean;
        BEGIN
            SELECT is_symmetric INTO symmetric_relation
            FROM corpus.proceeding_relation_concepts WHERE id=NEW.relation_concept_id;
            IF symmetric_relation AND NEW.source_proceeding_id::text > NEW.target_proceeding_id::text THEN
                RAISE EXCEPTION 'symmetric proceeding relations must use canonical UUID ordering' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER proceeding_relations_validate_symmetry BEFORE INSERT OR UPDATE OF source_proceeding_id,target_proceeding_id,relation_concept_id ON corpus.proceeding_relations FOR EACH ROW EXECUTE FUNCTION corpus.validate_proceeding_relation_symmetry()")

    op.execute("""
        CREATE OR REPLACE FUNCTION corpus.sync_judicial_event_type_concept()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        DECLARE is_state boolean;
        BEGIN
            IF NEW.event_type_concept_id IS NULL THEN
                SELECT id INTO NEW.event_type_concept_id
                FROM corpus.judicial_event_type_concepts
                WHERE code=NEW.status_type;
                IF NEW.event_type_concept_id IS NULL THEN
                    SELECT EXISTS(
                        SELECT 1 FROM corpus.decision_state_concepts
                        WHERE code=NEW.status_type
                    ) INTO is_state;
                    IF is_state THEN
                        RAISE EXCEPTION
                            'durative judicial state cannot be persisted as a point event: %',
                            NEW.status_type USING ERRCODE='23514';
                    END IF;
                    RAISE EXCEPTION 'unknown judicial event concept code: %',NEW.status_type
                        USING ERRCODE='23503';
                END IF;
            END IF;
            SELECT code INTO concept_code
            FROM corpus.judicial_event_type_concepts
            WHERE id=NEW.event_type_concept_id;
            IF concept_code IS NULL THEN
                RAISE EXCEPTION 'unknown judicial event concept' USING ERRCODE='23503';
            END IF;
            IF NEW.status_type IS NOT NULL AND NEW.status_type<>concept_code THEN
                RAISE EXCEPTION 'status_type conflicts with event_type_concept_id'
                    USING ERRCODE='23514';
            END IF;
            NEW.status_type:=concept_code;
            RETURN NEW;
        END $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION corpus.prepare_disposition_target_action()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE action_effect uuid;
        DECLARE next_ordinal integer;
        BEGIN
            IF NEW.action_id IS NULL THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(NEW.disposition_id::text, 3601)
                );
                SELECT coalesce(max(ordinal),0)+1 INTO next_ordinal
                FROM corpus.judicial_disposition_actions
                WHERE disposition_id=NEW.disposition_id;
                INSERT INTO corpus.judicial_disposition_actions(
                    scope_id,disposition_id,effect_concept_id,ordinal,
                    verification_status,verification_method
                ) VALUES(
                    NEW.scope_id,NEW.disposition_id,NEW.effect_concept_id,next_ordinal,
                    NEW.verification_status,NEW.verification_method
                ) RETURNING id INTO NEW.action_id;
            END IF;
            SELECT effect_concept_id INTO action_effect
            FROM corpus.judicial_disposition_actions
            WHERE id=NEW.action_id
              AND scope_id=NEW.scope_id
              AND disposition_id=NEW.disposition_id;
            IF action_effect IS NULL THEN
                RAISE EXCEPTION 'disposition target action does not belong to same clause/scope'
                    USING ERRCODE='23514';
            END IF;
            IF NEW.effect_concept_id IS NOT NULL AND NEW.effect_concept_id<>action_effect THEN
                RAISE EXCEPTION 'effect_concept_id conflicts with canonical disposition action'
                    USING ERRCODE='23514';
            END IF;
            NEW.effect_concept_id:=action_effect;
            RETURN NEW;
        END $$
    """)

    op.execute("COMMENT ON TABLE corpus.claim_relations IS 'Canonical lineage between claims/grounds across proceedings. It deliberately does not require the two claims to belong to the same proceeding.'")
    op.execute("COMMENT ON TABLE corpus.adjudicative_act_type_concepts IS 'Open legal vocabulary. Add observed forms as data; do not add CHECK-list migrations for jurisdiction-specific act types.'")
    op.execute("COMMENT ON TABLE corpus.judicial_event_type_concepts IS 'Open point-event vocabulary. Legal states such as finality/res judicata remain separate in decision_legal_states.'")


def downgrade() -> None:
    raise RuntimeError('0037 hardens the intentional pre-ingestion legal-reality normalization boundary')
