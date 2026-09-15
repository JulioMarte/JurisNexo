"""Enforce scope and evidence integrity for judicial intelligence links.

Revision ID: 0018_judicial_scope_integrity
Revises: 0017_judicial_proceedings
Create Date: 2026-09-14

The proceeding schema introduces new links between scoped canonical cases,
proceedings, and source records. These links must not become a path for joining
private and public corpus roots, and evidence pointers that claim to support a
decision-level fact must belong to that same decision.
"""

from alembic import op

revision = "0018_judicial_scope_integrity"
down_revision = "0017_judicial_proceedings"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def _add_scope_from_case(table: str, case_column: str) -> None:
    op.execute(
        f"ALTER TABLE corpus.{table} "
        f"ADD COLUMN scope_id uuid DEFAULT '{PUBLIC_SCOPE_ID}'::uuid"
    )
    op.execute(
        f"""
        UPDATE corpus.{table} linked
        SET scope_id = c.scope_id
        FROM corpus.cases c
        WHERE c.id = linked.{case_column}
        """
    )
    op.execute(f"ALTER TABLE corpus.{table} ALTER COLUMN scope_id SET NOT NULL")
    op.execute(
        f"""
        ALTER TABLE corpus.{table}
        ADD CONSTRAINT {table}_same_scope_case_fkey
            FOREIGN KEY (scope_id, {case_column})
            REFERENCES corpus.cases(scope_id, id)
        """
    )


def upgrade() -> None:
    _add_scope_from_case("case_proceedings", "case_id")
    op.execute(
        """
        ALTER TABLE corpus.case_proceedings
        ADD CONSTRAINT case_proceedings_same_scope_proceeding_fkey
            FOREIGN KEY (scope_id, proceeding_id)
            REFERENCES corpus.judicial_proceedings(scope_id, id)
        """
    )

    _add_scope_from_case("judicial_decision_relation_observations", "source_case_id")
    op.execute(
        """
        ALTER TABLE corpus.judicial_decision_relation_observations
        ADD CONSTRAINT judicial_decision_relation_observations_same_scope_target_fkey
            FOREIGN KEY (scope_id, target_case_id)
            REFERENCES corpus.cases(scope_id, id),
        ADD CONSTRAINT judicial_decision_relation_observations_evidence_same_case_fkey
            FOREIGN KEY (source_case_id, evidence_case_page_id)
            REFERENCES corpus.case_pages(case_id, id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    _add_scope_from_case("judicial_decision_relations", "source_case_id")
    op.execute(
        """
        ALTER TABLE corpus.judicial_decision_relations
        ADD CONSTRAINT judicial_decision_relations_same_scope_target_fkey
            FOREIGN KEY (scope_id, target_case_id)
            REFERENCES corpus.cases(scope_id, id)
        """
    )

    _add_scope_from_case("case_dispositions", "case_id")
    op.execute(
        """
        ALTER TABLE corpus.case_dispositions
        ADD CONSTRAINT case_dispositions_same_scope_affected_case_fkey
            FOREIGN KEY (scope_id, affected_case_id)
            REFERENCES corpus.cases(scope_id, id),
        ADD CONSTRAINT case_dispositions_same_scope_proceeding_fkey
            FOREIGN KEY (scope_id, affected_proceeding_id)
            REFERENCES corpus.judicial_proceedings(scope_id, id),
        ADD CONSTRAINT case_dispositions_evidence_same_case_fkey
            FOREIGN KEY (case_id, evidence_case_page_id)
            REFERENCES corpus.case_pages(case_id, id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    _add_scope_from_case("case_judicial_officers", "case_id")
    op.execute(
        """
        ALTER TABLE corpus.case_judicial_officers
        ADD CONSTRAINT case_judicial_officers_evidence_same_case_fkey
            FOREIGN KEY (case_id, evidence_case_page_id)
            REFERENCES corpus.case_pages(case_id, id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.execute(
        f"""
        ALTER TABLE corpus.source_document_canonical_resolutions
        ADD COLUMN scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
        ADD CONSTRAINT source_document_canonical_resolutions_public_scope_check
            CHECK (scope_id = '{PUBLIC_SCOPE_ID}'::uuid),
        ADD CONSTRAINT source_document_canonical_resolutions_same_scope_document_fkey
            FOREIGN KEY (scope_id, legal_document_id)
            REFERENCES corpus.legal_documents(scope_id, id)
        """
    )

    for table in (
        "case_proceedings",
        "judicial_decision_relation_observations",
        "judicial_decision_relations",
        "case_dispositions",
        "case_judicial_officers",
    ):
        op.execute(
            f"CREATE INDEX {table}_scope_idx ON corpus.{table} (scope_id)"
        )

    op.execute(
        """
        COMMENT ON COLUMN corpus.source_document_canonical_resolutions.scope_id IS
        'Official source inventory is public-corpus evidence. Canonical resolution therefore cannot silently attach an official source record to a tenant-private legal document.'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.source_document_canonical_resolutions
        DROP CONSTRAINT IF EXISTS source_document_canonical_resolutions_same_scope_document_fkey,
        DROP CONSTRAINT IF EXISTS source_document_canonical_resolutions_public_scope_check,
        DROP COLUMN IF EXISTS scope_id
        """
    )

    op.execute(
        """
        ALTER TABLE corpus.case_judicial_officers
        DROP CONSTRAINT IF EXISTS case_judicial_officers_evidence_same_case_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.case_dispositions
        DROP CONSTRAINT IF EXISTS case_dispositions_evidence_same_case_fkey,
        DROP CONSTRAINT IF EXISTS case_dispositions_same_scope_proceeding_fkey,
        DROP CONSTRAINT IF EXISTS case_dispositions_same_scope_affected_case_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.judicial_decision_relations
        DROP CONSTRAINT IF EXISTS judicial_decision_relations_same_scope_target_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.judicial_decision_relation_observations
        DROP CONSTRAINT IF EXISTS judicial_decision_relation_observations_evidence_same_case_fkey,
        DROP CONSTRAINT IF EXISTS judicial_decision_relation_observations_same_scope_target_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.case_proceedings
        DROP CONSTRAINT IF EXISTS case_proceedings_same_scope_proceeding_fkey
        """
    )

    for table in (
        "case_judicial_officers",
        "case_dispositions",
        "judicial_decision_relations",
        "judicial_decision_relation_observations",
        "case_proceedings",
    ):
        op.execute(f"DROP INDEX IF EXISTS corpus.{table}_scope_idx")
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            DROP CONSTRAINT IF EXISTS {table}_same_scope_case_fkey,
            DROP COLUMN IF EXISTS scope_id
            """
        )
