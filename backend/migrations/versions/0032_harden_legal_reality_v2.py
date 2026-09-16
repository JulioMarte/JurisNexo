"""Harden temporal and scope invariants introduced by legal reality v2.

Revision ID: 0032_harden_legal_reality_v2
Revises: 0031_legal_reality_v2
Create Date: 2026-09-16
"""

from alembic import op

revision = "0032_harden_legal_reality_v2"
down_revision = "0031_legal_reality_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0028 keyed norm-history overlap by proposition_id. After 0031 the same
    # proposition may legitimately ground multiple contextual norm claims.
    op.execute(
        "DROP TRIGGER IF EXISTS legal_norm_assertions_no_knowledge_overlap "
        "ON corpus.legal_norm_assertions"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.reject_norm_knowledge_overlap()")
    op.execute(
        """
        CREATE FUNCTION corpus.reject_norm_claim_knowledge_overlap() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.norm_claim_id::text, 3201)
            );
            IF EXISTS (
                SELECT 1
                FROM corpus.legal_norm_assertions a
                WHERE a.id <> NEW.id
                  AND a.norm_claim_id = NEW.norm_claim_id
                  AND tstzrange(a.known_from, a.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping legal norm claim knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_norm_assertions_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.legal_norm_assertions "
        "FOR EACH ROW EXECUTE FUNCTION corpus.reject_norm_claim_knowledge_overlap()"
    )
    op.execute(
        "ALTER TABLE corpus.legal_norm_assertions "
        "ALTER COLUMN norm_claim_id SET NOT NULL"
    )

    # Participant/officer/authority specializations are tenant-scoped views of
    # one shared legal entity identity. Enforce that scope in the database.
    op.execute(
        "ALTER TABLE corpus.participants "
        "ADD CONSTRAINT participants_same_scope_legal_entity_fkey "
        "FOREIGN KEY (scope_id, legal_entity_id) "
        "REFERENCES corpus.legal_entities(scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_officers "
        "ADD CONSTRAINT judicial_officers_same_scope_legal_entity_fkey "
        "FOREIGN KEY (scope_id, legal_entity_id) "
        "REFERENCES corpus.legal_entities(scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_authorities "
        "ADD CONSTRAINT legal_authorities_same_scope_legal_entity_fkey "
        "FOREIGN KEY (scope_id, legal_entity_id) "
        "REFERENCES corpus.legal_entities(scope_id, id)"
    )

    # New specializations should never be created without a common identity.
    # The insert triggers in 0031 populate these values before NOT NULL checks.
    op.execute("ALTER TABLE corpus.participants ALTER COLUMN legal_entity_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.judicial_officers ALTER COLUMN legal_entity_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.courts ALTER COLUMN legal_entity_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.legal_authorities ALTER COLUMN legal_entity_id SET NOT NULL")


def downgrade() -> None:
    raise RuntimeError("0032 is part of the intentional pre-ingestion normalization boundary")
