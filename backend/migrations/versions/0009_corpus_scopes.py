"""Add durable public/private corpus scopes.

Revision ID: 0009_corpus_scopes
Revises: 0008_quarantine_legacy_public
Create Date: 2026-09-12

The original corpus schema predates multi-organization access boundaries. This
migration introduces a durable scope root without coupling corpus records to a
particular authentication provider. Existing corpus rows are classified as
public because the pre-scope corpus contains the shared legal corpus; private
records must opt into an organization scope explicitly.
"""

from alembic import op

revision = "0009_corpus_scopes"
down_revision = "0008_quarantine_legacy_public"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.scopes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            visibility text NOT NULL,
            organization_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT corpus_scopes_visibility_check
                CHECK (visibility IN ('public', 'private')),
            CONSTRAINT corpus_scopes_ownership_check
                CHECK (
                    (visibility = 'public' AND organization_id IS NULL)
                    OR
                    (visibility = 'private' AND organization_id IS NOT NULL)
                )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX corpus_scopes_public_singleton_idx
        ON corpus.scopes (visibility)
        WHERE visibility = 'public'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX corpus_scopes_private_org_idx
        ON corpus.scopes (organization_id)
        WHERE visibility = 'private'
        """
    )
    op.execute(
        f"""
        INSERT INTO corpus.scopes (id, visibility)
        VALUES ('{PUBLIC_SCOPE_ID}'::uuid, 'public')
        """
    )

    for table in ("source_artifacts", "cases"):
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            ADD COLUMN scope_id uuid
            """
        )
        op.execute(
            f"""
            UPDATE corpus.{table}
            SET scope_id = '{PUBLIC_SCOPE_ID}'::uuid
            WHERE scope_id IS NULL
            """
        )
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            ALTER COLUMN scope_id SET NOT NULL,
            ALTER COLUMN scope_id SET DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            ADD CONSTRAINT {table}_scope_fk
                FOREIGN KEY (scope_id) REFERENCES corpus.scopes(id)
            """
        )
        op.execute(
            f"CREATE INDEX {table}_scope_idx ON corpus.{table} (scope_id)"
        )

    op.execute(
        """
        COMMENT ON TABLE corpus.scopes IS
        'Provider-neutral corpus visibility boundary. Public scope is shared; private scopes are owned by one external organization UUID.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.scopes.organization_id IS
        'External organization identifier resolved by trusted server authentication/authorization code; not supplied by agents.'
        """
    )


def downgrade() -> None:
    for table in ("cases", "source_artifacts"):
        op.execute(f"DROP INDEX IF EXISTS corpus.{table}_scope_idx")
        op.execute(
            f"""
            ALTER TABLE corpus.{table}
            DROP CONSTRAINT IF EXISTS {table}_scope_fk,
            DROP COLUMN IF EXISTS scope_id
            """
        )
    op.execute("DROP TABLE IF EXISTS corpus.scopes")
