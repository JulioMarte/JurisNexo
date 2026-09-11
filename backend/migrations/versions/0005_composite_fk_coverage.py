"""Cover composite provenance foreign keys and require parser code revisions.

Revision ID: 0005_composite_fk_coverage
Revises: 0004_ingest_observations
Create Date: 2026-09-11
"""

from alembic import op

revision = "0005_composite_fk_coverage"
down_revision = "0004_ingest_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These indexes mirror the composite FK column order used to prove that an
    # evidence page belongs to the same canonical case. PostgreSQL does not add
    # indexes on the referencing side automatically.
    op.execute(
        "CREATE INDEX case_identifiers_same_case_evidence_idx "
        "ON corpus.case_identifiers (case_id, evidence_case_page_id) "
        "WHERE evidence_case_page_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX case_metadata_observations_same_case_evidence_idx "
        "ON corpus.case_metadata_observations (case_id, evidence_case_page_id) "
        "WHERE evidence_case_page_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX cases_same_case_date_evidence_idx "
        "ON corpus.cases (id, decision_date_evidence_case_page_id) "
        "WHERE decision_date_evidence_case_page_id IS NOT NULL"
    )

    # Parser output is only reproducible if every parser version identifies the
    # code revision that produced it. The table is still empty at this stage, so
    # this can be tightened without a data backfill or synthetic placeholder.
    op.execute(
        "ALTER TABLE corpus.parser_versions "
        "ALTER COLUMN code_revision SET NOT NULL"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.parser_versions.code_revision IS "
        "'Immutable source-code revision or equivalent content identifier used to reproduce this parser version.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE corpus.parser_versions "
        "ALTER COLUMN code_revision DROP NOT NULL"
    )
    op.execute("DROP INDEX IF EXISTS corpus.cases_same_case_date_evidence_idx")
    op.execute(
        "DROP INDEX IF EXISTS corpus.case_metadata_observations_same_case_evidence_idx"
    )
    op.execute("DROP INDEX IF EXISTS corpus.case_identifiers_same_case_evidence_idx")
