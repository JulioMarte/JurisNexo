"""Enforce same-case page provenance for extracted legal metadata.

Revision ID: 0003_case_page_provenance
Revises: 0002_harden_migration_metadata
Create Date: 2026-09-10
"""

from alembic import op

revision = "0003_case_page_provenance"
down_revision = "0002_harden_migration_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A metadata evidence pointer must resolve to a page that belongs to the same
    # canonical case, not merely to any page in any source artifact.
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "ADD CONSTRAINT case_pages_case_id_id_key UNIQUE (case_id, id)"
    )

    op.execute(
        "ALTER TABLE corpus.cases "
        "DROP CONSTRAINT cases_decision_date_evidence_page_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "RENAME COLUMN decision_date_evidence_page_id TO decision_date_evidence_case_page_id"
    )
    op.execute(
        "ALTER INDEX corpus.cases_decision_date_evidence_page_idx "
        "RENAME TO cases_decision_date_evidence_case_page_idx"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "ADD CONSTRAINT cases_decision_date_evidence_same_case_fkey "
        "FOREIGN KEY (id, decision_date_evidence_case_page_id) "
        "REFERENCES corpus.case_pages (case_id, id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )

    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "DROP CONSTRAINT case_identifiers_evidence_page_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "RENAME COLUMN evidence_page_id TO evidence_case_page_id"
    )
    op.execute(
        "ALTER INDEX corpus.case_identifiers_evidence_page_idx "
        "RENAME TO case_identifiers_evidence_case_page_idx"
    )
    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "ADD CONSTRAINT case_identifiers_evidence_same_case_fkey "
        "FOREIGN KEY (case_id, evidence_case_page_id) "
        "REFERENCES corpus.case_pages (case_id, id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )

    op.execute(
        "COMMENT ON COLUMN corpus.cases.decision_date_evidence_case_page_id IS "
        "'Case-owned page containing the primary evidence for decision_date. Composite FK prevents cross-case provenance.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.case_identifiers.evidence_case_page_id IS "
        "'Case-owned page containing the identifier evidence. Composite FK prevents cross-case provenance.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "DROP CONSTRAINT case_identifiers_evidence_same_case_fkey"
    )
    op.execute(
        "ALTER INDEX corpus.case_identifiers_evidence_case_page_idx "
        "RENAME TO case_identifiers_evidence_page_idx"
    )
    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "RENAME COLUMN evidence_case_page_id TO evidence_page_id"
    )
    op.execute(
        "ALTER TABLE corpus.case_identifiers "
        "ADD CONSTRAINT case_identifiers_evidence_page_id_fkey "
        "FOREIGN KEY (evidence_page_id) REFERENCES corpus.artifact_pages (id)"
    )

    op.execute(
        "ALTER TABLE corpus.cases "
        "DROP CONSTRAINT cases_decision_date_evidence_same_case_fkey"
    )
    op.execute(
        "ALTER INDEX corpus.cases_decision_date_evidence_case_page_idx "
        "RENAME TO cases_decision_date_evidence_page_idx"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "RENAME COLUMN decision_date_evidence_case_page_id TO decision_date_evidence_page_id"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "ADD CONSTRAINT cases_decision_date_evidence_page_id_fkey "
        "FOREIGN KEY (decision_date_evidence_page_id) REFERENCES corpus.artifact_pages (id)"
    )

    op.execute(
        "ALTER TABLE corpus.case_pages "
        "DROP CONSTRAINT case_pages_case_id_id_key"
    )
