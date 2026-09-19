"""Synchronize compatibility fields with canonical legal-reality relations.

Revision ID: 0033_legal_reality_compat_sync
Revises: 0032_harden_legal_reality_v2
Create Date: 2026-09-16
"""

from alembic import op

revision = "0033_legal_reality_compat_sync"
down_revision = "0032_harden_legal_reality_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _sync_legacy_decision_classification()
    _sync_legacy_controversy_membership()
    _sync_legacy_opinion_author()
    _enforce_claim_disposition_membership()


def _sync_legacy_decision_classification() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.sync_legacy_decision_classification() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.legal_matter_concept_id IS NOT NULL THEN
                INSERT INTO corpus.decision_legal_matters (
                    scope_id, decision_id, legal_matter_concept_id,
                    relation_type, verification_status, verification_method
                ) VALUES (
                    NEW.scope_id, NEW.id, NEW.legal_matter_concept_id,
                    'primary', 'candidate', 'legacy_compatibility_field'
                ) ON CONFLICT DO NOTHING;
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
        "CREATE TRIGGER judicial_decisions_sync_legacy_classification "
        "AFTER INSERT OR UPDATE OF legal_matter_concept_id, procedure_concept_id "
        "ON corpus.judicial_decisions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.sync_legacy_decision_classification()"
    )
    op.execute(
        """
        INSERT INTO corpus.decision_legal_matters (
            scope_id, decision_id, legal_matter_concept_id,
            relation_type, verification_status, verification_method
        )
        SELECT scope_id, id, legal_matter_concept_id,
               'primary', 'candidate', 'legacy_compatibility_backfill'
        FROM corpus.judicial_decisions
        WHERE legal_matter_concept_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO corpus.decision_procedures (
            scope_id, decision_id, procedure_concept_id,
            relation_type, verification_status, verification_method
        )
        SELECT scope_id, id, procedure_concept_id,
               'primary', 'candidate', 'legacy_compatibility_backfill'
        FROM corpus.judicial_decisions
        WHERE procedure_concept_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def _sync_legacy_controversy_membership() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.sync_legacy_proceeding_controversy() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
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
    op.execute(
        "CREATE TRIGGER legal_proceedings_sync_legacy_controversy "
        "AFTER INSERT OR UPDATE OF controversy_id ON corpus.legal_proceedings "
        "FOR EACH ROW EXECUTE FUNCTION corpus.sync_legacy_proceeding_controversy()"
    )
    op.execute(
        """
        INSERT INTO corpus.controversy_proceedings (
            scope_id, controversy_id, proceeding_id, relation_type,
            verification_status, verification_method
        )
        SELECT scope_id, controversy_id, id, 'related',
               'candidate', 'legacy_compatibility_backfill'
        FROM corpus.legal_proceedings
        WHERE controversy_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def _sync_legacy_opinion_author() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.sync_legacy_opinion_author() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.author_officer_id IS NOT NULL
               AND OLD.author_officer_id IS DISTINCT FROM NEW.author_officer_id THEN
                DELETE FROM corpus.judicial_opinion_authors
                WHERE opinion_id = NEW.id
                  AND officer_id = OLD.author_officer_id
                  AND authorship_role = 'legacy_primary_author';
            END IF;
            IF NEW.author_officer_id IS NOT NULL THEN
                INSERT INTO corpus.judicial_opinion_authors (
                    scope_id, opinion_id, case_id, officer_id,
                    authorship_role, ordinal
                ) VALUES (
                    NEW.scope_id, NEW.id, NEW.case_id, NEW.author_officer_id,
                    'legacy_primary_author', 1
                ) ON CONFLICT DO NOTHING;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER judicial_opinions_sync_legacy_author "
        "AFTER INSERT OR UPDATE OF author_officer_id ON corpus.judicial_opinions "
        "FOR EACH ROW EXECUTE FUNCTION corpus.sync_legacy_opinion_author()"
    )


def _enforce_claim_disposition_membership() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.validate_disposition_claim_membership() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE claim_proceeding uuid;
        DECLARE disposition_decision uuid;
        BEGIN
            SELECT proceeding_id INTO claim_proceeding
            FROM corpus.legal_claims WHERE id = NEW.claim_id;
            SELECT case_id INTO disposition_decision
            FROM corpus.judicial_decision_dispositions WHERE id = NEW.disposition_id;

            IF claim_proceeding IS NULL OR disposition_decision IS NULL THEN
                RAISE EXCEPTION 'unknown claim or judicial disposition'
                    USING ERRCODE = '23503';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM corpus.proceeding_decisions pd
                WHERE pd.proceeding_id = claim_proceeding
                  AND pd.case_id = disposition_decision
                  AND pd.verification_status NOT IN ('rejected', 'superseded')
            ) THEN
                RAISE EXCEPTION 'disposition cannot resolve a claim from an unrelated proceeding'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER disposition_claim_effects_validate_membership "
        "BEFORE INSERT OR UPDATE OF disposition_id, claim_id "
        "ON corpus.disposition_claim_effects FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_disposition_claim_membership()"
    )


def downgrade() -> None:
    raise RuntimeError("0033 is part of the intentional pre-ingestion normalization boundary")
