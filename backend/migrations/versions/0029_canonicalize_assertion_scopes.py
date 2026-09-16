"""Derive assertion scopes from their canonical parents.

Revision ID: 0029_assertion_scopes
Revises: 0028_harden_assert_history
Create Date: 2026-09-16
"""

from alembic import op

revision = "0029_assertion_scopes"
down_revision = "0028_harden_assert_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_norm_source_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            SELECT a.scope_id INTO NEW.assertion_scope_id
            FROM corpus.legal_norm_assertions a
            WHERE a.id = NEW.norm_assertion_id;
            IF NEW.assertion_scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown legal norm assertion'
                    USING ERRCODE = '23503';
            END IF;
            NEW.scope_id := NEW.assertion_scope_id;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER legal_norm_sources_canonical_scope
        BEFORE INSERT OR UPDATE OF norm_assertion_id
        ON corpus.legal_norm_sources
        FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_norm_source_scope()
        """
    )

    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_relation_identity_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            SELECT d.scope_id INTO NEW.scope_id
            FROM corpus.legal_documents d
            WHERE d.id = NEW.source_document_id;
            IF NEW.scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown source legal document'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER legal_relation_identities_canonical_scope
        BEFORE INSERT OR UPDATE OF source_document_id
        ON corpus.legal_relation_identities
        FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_relation_identity_scope()
        """
    )

    op.execute(
        """
        CREATE FUNCTION corpus.canonicalize_relation_assertion_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            SELECT r.scope_id INTO NEW.scope_id
            FROM corpus.legal_relation_identities r
            WHERE r.id = NEW.relation_identity_id;
            IF NEW.scope_id IS NULL THEN
                RAISE EXCEPTION 'unknown legal relation identity'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER legal_relation_assertions_canonical_scope
        BEFORE INSERT OR UPDATE OF relation_identity_id
        ON corpus.legal_relation_assertions
        FOR EACH ROW EXECUTE FUNCTION corpus.canonicalize_relation_assertion_scope()
        """
    )


def downgrade() -> None:
    raise RuntimeError("0029 is part of the pre-ingestion normalization boundary")
