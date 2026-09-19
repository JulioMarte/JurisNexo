"""Clean redundant disposition actions created by the V3 compatibility backfill.

Revision ID: 0038_cleanup_v3_backfill
Revises: 0037_harden_legal_reality_v3
Create Date: 2026-09-17

The pre-V3 schema stored an effect on every disposition target but had no action
identity. Revision 0036 therefore had to infer actions during backfill. When a
single clause had several targets with the same effect, the compatibility
backfill could create several candidate actions and then point every target at
the first one, leaving the remaining inferred rows unreferenced.

Those rows carry no information that did not already exist on the targets, so
keeping them would manufacture duplicate canonical facts. This migration
removes only such unreferenced, textless inferred actions.
"""

from alembic import op

revision = "0038_cleanup_v3_backfill"
down_revision = "0037_harden_legal_reality_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM corpus.judicial_disposition_actions a
        WHERE a.raw_action_text IS NULL
          AND a.condition_text IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM corpus.disposition_targets t
              WHERE t.action_id = a.id
          )
    """)
    op.execute("""
        COMMENT ON TABLE corpus.judicial_disposition_actions IS
        'Canonical actions expressed by a textual disposition clause; one clause may have many actions and one action may have many targets. V3 compatibility-backfill duplicates are removed by 0038.'
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0038 removes redundant inferred rows that contain no independent legal fact"
    )
