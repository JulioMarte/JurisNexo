"""JurisNexo PostgreSQL baseline.

Revision ID: baseline_20260919
Revises:
Create Date: 2026-09-19
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "baseline_20260919"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "baseline.sql"
    sql = sql_path.read_text(encoding="utf-8")
    driver_connection = op.get_bind().connection.driver_connection
    with driver_connection.cursor() as cursor:
        cursor.execute(sql, prepare=False)
        cursor.execute("SET search_path TO public", prepare=False)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS public.alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
            """,
            prepare=False,
        )
        cursor.execute(
            "ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY",
            prepare=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "The JurisNexo baseline is intentionally non-destructive. "
        "Restore from backup or recreate the database instead of downgrading it."
    )
