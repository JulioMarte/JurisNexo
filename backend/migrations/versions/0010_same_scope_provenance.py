"""Enforce same-scope case/artifact provenance.

Revision ID: 0010_same_scope_provenance
Revises: 0009_corpus_scopes
Create Date: 2026-09-12

Canonical case provenance crosses two durable roots: cases and source artifacts.
Both roots already carry scope_id, but link rows could still connect different
scopes unless PostgreSQL verifies the scope together with each identifier.
"""

from alembic import op

revision = "0010_same_scope_provenance"
down_revision = "0009_corpus_scopes"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.cases "
        "ADD CONSTRAINT cases_scope_id_id_key UNIQUE (scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.source_artifacts "
        "ADD CONSTRAINT source_artifacts_scope_id_id_key UNIQUE (scope_id, id)"
    )

    for table in ("case_artifact_occurrences", "case_pages"):
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            ADD COLUMN scope_id uuid DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
            """
        )
        op.execute(
            f"""
            UPDATE corpus.{table} linked
            SET scope_id = c.scope_id
            FROM corpus.cases c
            WHERE c.id = linked.case_id
            """
        )
        op.execute(
            f"ALTER TABLE corpus.{table} ALTER COLUMN scope_id SET NOT NULL"
        )
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            ADD CONSTRAINT {table}_same_scope_case_fkey
                FOREIGN KEY (scope_id, case_id)
                REFERENCES corpus.cases (scope_id, id),
            ADD CONSTRAINT {table}_same_scope_artifact_fkey
                FOREIGN KEY (scope_id, artifact_id)
                REFERENCES corpus.source_artifacts (scope_id, id)
            """
        )
        op.execute(
            f"CREATE INDEX {table}_scope_case_idx "
            f"ON corpus.{table} (scope_id, case_id)"
        )
        op.execute(
            f"CREATE INDEX {table}_scope_artifact_idx "
            f"ON corpus.{table} (scope_id, artifact_id)"
        )

    op.execute(
        """
        COMMENT ON COLUMN corpus.case_artifact_occurrences.scope_id IS
        'Scope shared by the canonical case and source artifact; public links default to the stable public scope while private links must name their private scope explicitly.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.case_pages.scope_id IS
        'Scope shared by the canonical case and source artifact page; public links default to the stable public scope while private links must name their private scope explicitly.'
        """
    )


def downgrade() -> None:
    for table in ("case_pages", "case_artifact_occurrences"):
        op.execute(f"DROP INDEX IF EXISTS corpus.{table}_scope_artifact_idx")
        op.execute(f"DROP INDEX IF EXISTS corpus.{table}_scope_case_idx")
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            DROP CONSTRAINT IF EXISTS {table}_same_scope_artifact_fkey,
            DROP CONSTRAINT IF EXISTS {table}_same_scope_case_fkey,
            DROP COLUMN IF EXISTS scope_id
            """
        )

    op.execute(
        "ALTER TABLE corpus.source_artifacts "
        "DROP CONSTRAINT IF EXISTS source_artifacts_scope_id_id_key"
    )
    op.execute(
        "ALTER TABLE corpus.cases "
        "DROP CONSTRAINT IF EXISTS cases_scope_id_id_key"
    )
