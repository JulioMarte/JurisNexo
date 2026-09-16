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

    op.execute("COMMENT ON TABLE corpus.claim_relations IS 'Canonical lineage between claims/grounds across proceedings. It deliberately does not require the two claims to belong to the same proceeding.'")
    op.execute("COMMENT ON TABLE corpus.adjudicative_act_type_concepts IS 'Open legal vocabulary. Add observed forms as data; do not add CHECK-list migrations for jurisdiction-specific act types.'")
    op.execute("COMMENT ON TABLE corpus.judicial_event_type_concepts IS 'Open point-event vocabulary. Legal states such as finality/res judicata remain separate in decision_legal_states.'")


def downgrade() -> None:
    raise RuntimeError('0037 hardens the intentional pre-ingestion legal-reality normalization boundary')
