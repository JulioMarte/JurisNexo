"""Harden disposition action/target semantic integrity.

Revision ID: 0041_harden_disposition_targets
Revises: 0040_open_legal_vocabularies
Create Date: 2026-09-17

Revision 0039 correctly removed disposition_targets.effect_concept_id so the
legal effect lives only on judicial_disposition_actions. That removal also
removed the old composite FK which had enforced that an effect's target_type
matched the concrete target row. Re-establish that invariant without restoring
a compatibility mirror, and prevent duplicate targets within one action.
"""

from alembic import op

revision = "0041_harden_disposition_targets"
down_revision = "0040_open_legal_vocabularies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.validate_disposition_action_target_type()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE effect_target_type text;
        BEGIN
            SELECT e.target_type INTO effect_target_type
            FROM corpus.judicial_disposition_actions a
            JOIN corpus.disposition_effect_concepts e
              ON e.id = a.effect_concept_id
            WHERE a.id = NEW.action_id
              AND a.scope_id = NEW.scope_id
              AND a.disposition_id = NEW.disposition_id;

            IF effect_target_type IS NULL THEN
                RAISE EXCEPTION
                    'disposition target action does not exist in the same scope/clause'
                    USING ERRCODE = '23503';
            END IF;

            IF effect_target_type <> NEW.target_type THEN
                RAISE EXCEPTION
                    'disposition action effect target type % conflicts with target type %',
                    effect_target_type, NEW.target_type
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER disposition_targets_validate_action_effect_type "
        "BEFORE INSERT OR UPDATE OF action_id,target_type,disposition_id,scope_id "
        "ON corpus.disposition_targets FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_disposition_action_target_type()"
    )

    op.execute(
        """
        CREATE FUNCTION corpus.validate_disposition_action_effect_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE effect_target_type text;
        BEGIN
            SELECT target_type INTO effect_target_type
            FROM corpus.disposition_effect_concepts
            WHERE id = NEW.effect_concept_id;

            IF effect_target_type IS NULL THEN
                RAISE EXCEPTION 'unknown disposition effect concept'
                    USING ERRCODE = '23503';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM corpus.disposition_targets t
                WHERE t.action_id = NEW.id
                  AND t.target_type <> effect_target_type
            ) THEN
                RAISE EXCEPTION
                    'disposition action effect target type % conflicts with existing targets',
                    effect_target_type
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_disposition_actions_validate_effect_change "
        "BEFORE UPDATE OF effect_concept_id "
        "ON corpus.judicial_disposition_actions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_disposition_action_effect_change()"
    )

    for target_type, column in (
        ("claim", "target_claim_id"),
        ("party", "target_party_role_id"),
        ("proceeding", "target_proceeding_id"),
        ("decision", "target_decision_id"),
        ("proposition", "target_proposition_id"),
    ):
        op.execute(
            f"CREATE UNIQUE INDEX disposition_targets_action_{target_type}_key "
            f"ON corpus.disposition_targets(action_id,{column}) "
            f"WHERE target_type='{target_type}'"
        )

    op.execute(
        """
        COMMENT ON TABLE corpus.disposition_targets IS
        'Targets of a canonical judicial_disposition_action. The action owns the legal effect; PostgreSQL enforces that the effect concept target type matches every target and that one action cannot repeat the same target.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0041 restores a canonical semantic invariant lost when the legacy effect mirror was removed"
    )
