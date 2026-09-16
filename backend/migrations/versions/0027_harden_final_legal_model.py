"""Harden the final pre-ingestion legal model.

Revision ID: 0027_harden_final_model
Revises: 0026_final_legal_model
Create Date: 2026-09-16
"""

from alembic import op

revision = "0027_harden_final_model"
down_revision = "0026_final_legal_model"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.legal_norm_sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            norm_assertion_id uuid NOT NULL REFERENCES corpus.legal_norm_assertions(id) ON DELETE CASCADE,
            source_document_id uuid NOT NULL,
            source_document_provision_id uuid,
            source_role text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_excerpt text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_norm_sources_role_check CHECK (source_role IN ('establishes','defines','amends','repeals','creates_exception','interprets','satisfies','evidences')),
            CONSTRAINT legal_norm_sources_status_check CHECK (verification_status IN ('candidate','verified','conflicting','rejected','superseded')),
            CONSTRAINT legal_norm_sources_same_scope_document_fkey FOREIGN KEY (scope_id, source_document_id) REFERENCES corpus.legal_documents(scope_id, id),
            CONSTRAINT legal_norm_sources_document_provision_fkey FOREIGN KEY (source_document_id, source_document_provision_id) REFERENCES corpus.legal_document_provisions(document_id, id),
            CONSTRAINT legal_norm_sources_unique UNIQUE NULLS NOT DISTINCT (norm_assertion_id, source_document_id, source_document_provision_id, source_role)
        )
        """
    )
    op.execute("CREATE INDEX legal_norm_sources_assertion_idx ON corpus.legal_norm_sources (norm_assertion_id, source_role, verification_status)")

    # A verified norm synthesis must have at least one source before it can be
    # marked verified. Enforce this transition deterministically.
    op.execute(
        """
        CREATE FUNCTION corpus.validate_verified_norm_sources() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status = 'verified' AND NOT EXISTS (
                SELECT 1 FROM corpus.legal_norm_sources s
                WHERE s.norm_assertion_id = NEW.id AND s.verification_status = 'verified'
            ) THEN
                RAISE EXCEPTION 'verified legal norm assertion requires verified source evidence' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER legal_norm_assertions_verified_sources AFTER INSERT OR UPDATE OF verification_status ON corpus.legal_norm_assertions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION corpus.validate_verified_norm_sources()"
    )

    # Keep one open knowledge assertion for materially identical precedent/status
    # claims. Historical corrections close the prior known interval first.
    op.execute(
        """
        CREATE UNIQUE INDEX precedential_authority_current_idx
        ON corpus.precedential_authority_assertions (
            decision_id,
            coalesce(proposition_id, '00000000-0000-0000-0000-000000000000'::uuid),
            authority_type,
            coalesce(jurisdiction_code, ''),
            coalesce(court_id, '00000000-0000-0000-0000-000000000000'::uuid),
            coalesce(legal_matter_concept_id, '00000000-0000-0000-0000-000000000000'::uuid)
        ) WHERE known_to IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX decision_legal_status_current_idx
        ON corpus.decision_legal_status_events (
            case_id, status_type, coalesce(occurred_on, '0001-01-01'::date)
        ) WHERE known_to IS NULL
        """
    )

    op.execute(
        "COMMENT ON TABLE corpus.legal_norm_sources IS "
        "'Typed legal-source support for a derived norm assertion. It preserves establishes/defines/exception/interprets semantics without treating synthesized norm text as primary-source text.'"
    )


def downgrade() -> None:
    raise RuntimeError("0027 is part of the intentional pre-ingestion normalization boundary")
