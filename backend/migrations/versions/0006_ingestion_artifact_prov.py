"""Bind ingestion observations to the artifact processed by their job.

Revision ID: 0006_ingestion_artifact_prov
Revises: 0005_composite_fk_coverage
Create Date: 2026-09-11
"""

from alembic import op

revision = "0006_ingestion_artifact_prov"
down_revision = "0005_composite_fk_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make artifact identity available on case_pages so provenance can be enforced
    # declaratively across case + page + artifact instead of by application code.
    op.execute("ALTER TABLE corpus.case_pages ADD COLUMN artifact_id uuid")
    op.execute(
        """
        UPDATE corpus.case_pages cp
        SET artifact_id = ap.artifact_id
        FROM corpus.artifact_pages ap
        WHERE ap.id = cp.artifact_page_id
        """
    )
    op.execute("ALTER TABLE corpus.case_pages ALTER COLUMN artifact_id SET NOT NULL")

    op.execute(
        "ALTER TABLE corpus.artifact_pages "
        "ADD CONSTRAINT artifact_pages_artifact_id_id_key UNIQUE (artifact_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "DROP CONSTRAINT case_pages_artifact_page_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "ADD CONSTRAINT case_pages_artifact_page_same_artifact_fkey "
        "FOREIGN KEY (artifact_id, artifact_page_id) "
        "REFERENCES corpus.artifact_pages (artifact_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "ADD CONSTRAINT case_pages_case_id_id_artifact_id_key "
        "UNIQUE (case_id, id, artifact_id)"
    )
    op.execute(
        "CREATE INDEX case_pages_artifact_page_provenance_idx "
        "ON corpus.case_pages (artifact_id, artifact_page_id)"
    )

    # Bind an observation to the artifact of its ingestion job and then require
    # its evidence case page to originate from that same artifact.
    op.execute("ALTER TABLE corpus.case_metadata_observations ADD COLUMN artifact_id uuid")
    op.execute(
        """
        UPDATE corpus.case_metadata_observations observation
        SET artifact_id = job.artifact_id
        FROM corpus.ingestion_jobs job
        WHERE job.id = observation.ingestion_job_id
        """
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ALTER COLUMN artifact_id SET NOT NULL"
    )

    op.execute(
        "ALTER TABLE corpus.ingestion_jobs "
        "ADD CONSTRAINT ingestion_jobs_id_artifact_id_key UNIQUE (id, artifact_id)"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "DROP CONSTRAINT case_metadata_observations_ingestion_job_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ADD CONSTRAINT case_metadata_observations_job_artifact_fkey "
        "FOREIGN KEY (ingestion_job_id, artifact_id) "
        "REFERENCES corpus.ingestion_jobs (id, artifact_id) ON DELETE CASCADE"
    )

    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "DROP CONSTRAINT case_metadata_observations_evidence_same_case_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ADD CONSTRAINT case_metadata_observations_evidence_same_case_artifact_fkey "
        "FOREIGN KEY (case_id, evidence_case_page_id, artifact_id) "
        "REFERENCES corpus.case_pages (case_id, id, artifact_id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )

    op.execute(
        "CREATE INDEX case_metadata_observations_job_artifact_idx "
        "ON corpus.case_metadata_observations (ingestion_job_id, artifact_id)"
    )
    op.execute(
        "CREATE INDEX case_metadata_observations_evidence_case_artifact_idx "
        "ON corpus.case_metadata_observations "
        "(case_id, evidence_case_page_id, artifact_id) "
        "WHERE evidence_case_page_id IS NOT NULL"
    )

    op.execute(
        "COMMENT ON COLUMN corpus.case_pages.artifact_id IS "
        "'Artifact owning artifact_page_id; duplicated intentionally so cross-artifact provenance is enforceable with foreign keys.'"
    )
    op.execute(
        "COMMENT ON COLUMN corpus.case_metadata_observations.artifact_id IS "
        "'Artifact processed by ingestion_job_id. Observation evidence must resolve to a case page from this same artifact.'"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS corpus.case_metadata_observations_evidence_case_artifact_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS corpus.case_metadata_observations_job_artifact_idx"
    )

    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "DROP CONSTRAINT case_metadata_observations_evidence_same_case_artifact_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ADD CONSTRAINT case_metadata_observations_evidence_same_case_fkey "
        "FOREIGN KEY (case_id, evidence_case_page_id) "
        "REFERENCES corpus.case_pages (case_id, id) "
        "DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "DROP CONSTRAINT case_metadata_observations_job_artifact_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_metadata_observations "
        "ADD CONSTRAINT case_metadata_observations_ingestion_job_id_fkey "
        "FOREIGN KEY (ingestion_job_id) REFERENCES corpus.ingestion_jobs(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE corpus.ingestion_jobs "
        "DROP CONSTRAINT ingestion_jobs_id_artifact_id_key"
    )
    op.execute("ALTER TABLE corpus.case_metadata_observations DROP COLUMN artifact_id")

    op.execute("DROP INDEX IF EXISTS corpus.case_pages_artifact_page_provenance_idx")
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "DROP CONSTRAINT case_pages_case_id_id_artifact_id_key"
    )
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "DROP CONSTRAINT case_pages_artifact_page_same_artifact_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.case_pages "
        "ADD CONSTRAINT case_pages_artifact_page_id_fkey "
        "FOREIGN KEY (artifact_page_id) REFERENCES corpus.artifact_pages(id)"
    )
    op.execute(
        "ALTER TABLE corpus.artifact_pages "
        "DROP CONSTRAINT artifact_pages_artifact_id_id_key"
    )
    op.execute("ALTER TABLE corpus.case_pages DROP COLUMN artifact_id")
