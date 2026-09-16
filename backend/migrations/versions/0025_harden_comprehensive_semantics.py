"""Harden semantic scope and concurrent invariants.

Revision ID: 0025_harden_semantics
Revises: 0024_comprehensive_semantics
Create Date: 2026-09-16

Serializes the small critical sections used to validate taxonomy cycles and
bitemporal knowledge intervals, and scope-qualifies treatment evidence.
"""

from alembic import op

revision = "0025_harden_semantics"
down_revision = "0024_comprehensive_semantics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.legal_proposition_evidence "
        "ADD CONSTRAINT legal_proposition_evidence_scope_id_id_key UNIQUE (scope_id, id)"
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_treatment_assertions
        ADD CONSTRAINT legal_treatment_assertions_same_scope_evidence_fkey
        FOREIGN KEY (scope_id, evidence_id)
        REFERENCES corpus.legal_proposition_evidence(scope_id, id)
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.reject_matter_concept_cycle() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('legal-matter-taxonomy', 0));
            IF NEW.relation_type IN ('broader', 'part_of') AND EXISTS (
                WITH RECURSIVE ancestors(id) AS (
                    SELECT NEW.broader_concept_id
                    UNION
                    SELECT edge.broader_concept_id
                    FROM corpus.legal_matter_concept_edges edge
                    JOIN ancestors a ON edge.narrower_concept_id = a.id
                    WHERE edge.relation_type IN ('broader', 'part_of')
                )
                SELECT 1 FROM ancestors WHERE id = NEW.narrower_concept_id
            ) THEN
                RAISE EXCEPTION 'legal matter taxonomy cycle' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.reject_procedure_concept_cycle() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended('procedure-taxonomy', 0));
            IF NEW.relation_type IN ('broader', 'part_of') AND EXISTS (
                WITH RECURSIVE ancestors(id) AS (
                    SELECT NEW.broader_concept_id
                    UNION
                    SELECT edge.broader_concept_id
                    FROM corpus.procedure_concept_edges edge
                    JOIN ancestors a ON edge.narrower_concept_id = a.id
                    WHERE edge.relation_type IN ('broader', 'part_of')
                )
                SELECT 1 FROM ancestors WHERE id = NEW.narrower_concept_id
            ) THEN
                RAISE EXCEPTION 'procedure taxonomy cycle' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.reject_instrument_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.instrument_version_id::text, 2025)
            );
            IF EXISTS (
                SELECT 1 FROM corpus.legal_instrument_version_knowledge k
                WHERE k.instrument_version_id = NEW.instrument_version_id
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping instrument knowledge time'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.reject_provision_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.provision_version_id::text, 2025)
            );
            IF EXISTS (
                SELECT 1 FROM corpus.legal_provision_version_knowledge k
                WHERE k.provision_version_id = NEW.provision_version_id
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping provision knowledge time'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.legal_treatment_assertions "
        "DROP CONSTRAINT IF EXISTS legal_treatment_assertions_same_scope_evidence_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.legal_proposition_evidence "
        "DROP CONSTRAINT IF EXISTS legal_proposition_evidence_scope_id_id_key"
    )
    # The original non-locking functions are restored by downgrading 0024.
