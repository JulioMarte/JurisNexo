"""Harden Alembic metadata and add covering foreign-key indexes.

Revision ID: 0002_harden_migration_metadata
Revises: 0001_initial_corpus_schema
Create Date: 2026-09-10
"""

from alembic import op

revision = "0002_harden_migration_metadata"
down_revision = "0001_initial_corpus_schema"
branch_labels = None
depends_on = None


def _revoke_from_supabase_role(role_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM {role_name}';
            END IF;
        END
        $$
        """
    )


def _grant_select_to_supabase_role(role_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                EXECUTE 'GRANT SELECT ON TABLE public.alembic_version TO {role_name}';
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    # Alembic's version table lives in the exposed public schema by default.
    # It is internal deployment metadata, not application data. Keep Alembic's
    # conventional location for operational simplicity, but make it unreadable
    # through Supabase client roles and enable RLS as defense in depth.
    op.execute("ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY")
    _revoke_from_supabase_role("anon")
    _revoke_from_supabase_role("authenticated")

    # PostgreSQL does not automatically index referencing foreign-key columns.
    # These indexes cover joins and parent-row maintenance paths identified by
    # the Supabase performance advisor after the initial schema was applied.
    op.execute(
        "CREATE INDEX source_artifacts_source_registry_idx "
        "ON corpus.source_artifacts (source_registry_id)"
    )
    op.execute(
        "CREATE INDEX cases_decision_date_evidence_page_idx "
        "ON corpus.cases (decision_date_evidence_page_id) "
        "WHERE decision_date_evidence_page_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX case_identifiers_case_idx "
        "ON corpus.case_identifiers (case_id)"
    )
    op.execute(
        "CREATE INDEX case_identifiers_evidence_page_idx "
        "ON corpus.case_identifiers (evidence_page_id) "
        "WHERE evidence_page_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS corpus.case_identifiers_evidence_page_idx")
    op.execute("DROP INDEX IF EXISTS corpus.case_identifiers_case_idx")
    op.execute("DROP INDEX IF EXISTS corpus.cases_decision_date_evidence_page_idx")
    op.execute("DROP INDEX IF EXISTS corpus.source_artifacts_source_registry_idx")

    # A downgrade restores the conventional Alembic table posture only when the
    # Supabase-specific roles exist. Production should not normally do this.
    _grant_select_to_supabase_role("anon")
    _grant_select_to_supabase_role("authenticated")
    op.execute("ALTER TABLE public.alembic_version DISABLE ROW LEVEL SECURITY")
