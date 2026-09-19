"""Enforce verified legal norm sources immediately.

Revision ID: 0030_verified_norm_sources
Revises: 0029_assertion_scopes
Create Date: 2026-09-16

A verified derived/synthesized norm must never be observable without at least
one verified legal source. The earlier constraint trigger was deferred, which
allowed the invalid state to survive until the outer transaction boundary and
made savepoint-scoped verification semantically weaker than intended.
"""

from alembic import op

revision = "0030_verified_norm_sources"
down_revision = "0029_assertion_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER legal_norm_assertions_verified_sources "
        "ON corpus.legal_norm_assertions"
    )
    op.execute(
        """
        CREATE TRIGGER legal_norm_assertions_verified_sources
        AFTER INSERT OR UPDATE OF verification_status
        ON corpus.legal_norm_assertions
        FOR EACH ROW
        EXECUTE FUNCTION corpus.validate_verified_norm_sources()
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0030 is part of the intentional pre-ingestion normalization boundary"
    )
