"""Add canonical legal relation graph schema.

Revision ID: 0014_legal_graph
Revises: 0013_source_collection
Create Date: 2026-09-12

Documents remain the canonical legal works, artifacts remain immutable source
bytes, and this revision adds provision-level structure, auditable relation
observations, verified canonical relations, requirements, and independent
classification tags.
"""

from alembic import op

revision = "0014_legal_graph"
down_revision = "0013_source_collection"
branch_labels = None
depends_on = None

RELATION_TYPES = (
    "cites",
    "references",
    "interprets",
    "applies",
    "declines_to_apply",
    "follows",
    "distinguishes",
    "overrules",
    "authorized_by",
    "implements",
    "amends",
    "repeals",
    "partially_repeals",
    "supersedes",
    "conflicts_with",
    "consistent_with",
    "requires",
    "satisfies",
    "exempts_from",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    relation_types = _sql_list(RELATION_TYPES)

    op.execute(
        """
        CREATE TABLE corpus.legal_document_provisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            parent_provision_id uuid,
            provision_type text NOT NULL,
            label text,
            normalized_label text,
            ordinal integer,
            heading text,
            text text,
            effective_from date,
            effective_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_document_provisions_type_check CHECK (
                provision_type = ANY (ARRAY[
                    'title', 'book', 'chapter', 'section', 'article', 'paragraph',
                    'clause', 'subclause', 'item', 'annex', 'preamble', 'other'
                ]::text[])
            ),
            CONSTRAINT legal_document_provisions_ordinal_check CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT legal_document_provisions_effective_range_check CHECK (
                effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT legal_document_provisions_document_id_id_key UNIQUE (document_id, id),
            CONSTRAINT legal_document_provisions_parent_same_document_fkey
                FOREIGN KEY (document_id, parent_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX legal_document_provisions_label_key "
        "ON corpus.legal_document_provisions (document_id, normalized_label) "
        "WHERE normalized_label IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX legal_document_provisions_parent_idx "
        "ON corpus.legal_document_provisions (parent_provision_id) "
        "WHERE parent_provision_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX legal_document_provisions_document_ordinal_idx "
        "ON corpus.legal_document_provisions (document_id, ordinal)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_relation_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            ingestion_job_id uuid REFERENCES corpus.ingestion_jobs(id) ON DELETE SET NULL,
            observation_key text NOT NULL UNIQUE,
            source_document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            source_provision_id uuid,
            relation_type text NOT NULL,
            target_document_id uuid REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            target_provision_id uuid,
            raw_target_citation text,
            assertion_method text NOT NULL,
            method_name text NOT NULL,
            confidence real,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_excerpt text,
            evidence_char_start integer,
            evidence_char_end integer,
            status text NOT NULL DEFAULT 'observed',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relation_observations_key_check CHECK (observation_key ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT legal_relation_observations_type_check CHECK (relation_type IN ({relation_types})),
            CONSTRAINT legal_relation_observations_method_check CHECK (
                assertion_method IN (
                    'explicit_primary_text',
                    'official_metadata',
                    'deterministic_reference',
                    'llm_extracted',
                    'human_verified'
                )
            ),
            CONSTRAINT legal_relation_observations_status_check CHECK (
                status IN ('observed', 'accepted', 'rejected', 'conflicting', 'superseded')
            ),
            CONSTRAINT legal_relation_observations_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            ),
            CONSTRAINT legal_relation_observations_target_check CHECK (
                target_document_id IS NOT NULL OR btrim(coalesce(raw_target_citation, '')) <> ''
            ),
            CONSTRAINT legal_relation_observations_target_provision_check CHECK (
                target_provision_id IS NULL OR target_document_id IS NOT NULL
            ),
            CONSTRAINT legal_relation_observations_offsets_check CHECK (
                (evidence_char_start IS NULL AND evidence_char_end IS NULL)
                OR (
                    evidence_char_start IS NOT NULL
                    AND evidence_char_end IS NOT NULL
                    AND evidence_char_start >= 0
                    AND evidence_char_end > evidence_char_start
                )
            ),
            CONSTRAINT legal_relation_observations_source_provision_fkey
                FOREIGN KEY (source_document_id, source_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT legal_relation_observations_target_provision_fkey
                FOREIGN KEY (target_document_id, target_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_relation_observations_source_idx "
        "ON corpus.legal_relation_observations (source_document_id, relation_type, status)"
    )
    op.execute(
        "CREATE INDEX legal_relation_observations_target_idx "
        "ON corpus.legal_relation_observations (target_document_id, relation_type, status) "
        "WHERE target_document_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX legal_relation_observations_evidence_page_idx "
        "ON corpus.legal_relation_observations (evidence_artifact_page_id) "
        "WHERE evidence_artifact_page_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.legal_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            source_provision_id uuid,
            relation_type text NOT NULL,
            target_document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            target_provision_id uuid,
            status text NOT NULL DEFAULT 'verified',
            effective_from date,
            effective_to date,
            verification_method text NOT NULL,
            promoted_from_observation_id uuid REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relations_type_check CHECK (relation_type IN ({relation_types})),
            CONSTRAINT legal_relations_status_check CHECK (
                status IN ('verified', 'conflicting', 'superseded')
            ),
            CONSTRAINT legal_relations_effective_range_check CHECK (
                effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT legal_relations_source_provision_fkey
                FOREIGN KEY (source_document_id, source_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT legal_relations_target_provision_fkey
                FOREIGN KEY (target_document_id, target_provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX legal_relations_identity_key
        ON corpus.legal_relations (
            source_document_id,
            coalesce(source_provision_id, '00000000-0000-0000-0000-000000000000'::uuid),
            relation_type,
            target_document_id,
            coalesce(target_provision_id, '00000000-0000-0000-0000-000000000000'::uuid)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_relations_source_idx "
        "ON corpus.legal_relations (source_document_id, relation_type, status)"
    )
    op.execute(
        "CREATE INDEX legal_relations_target_idx "
        "ON corpus.legal_relations (target_document_id, relation_type, status)"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_relation_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            relation_id uuid NOT NULL REFERENCES corpus.legal_relations(id) ON DELETE CASCADE,
            observation_id uuid REFERENCES corpus.legal_relation_observations(id) ON DELETE SET NULL,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_kind text NOT NULL,
            evidence_excerpt text,
            evidence_char_start integer,
            evidence_char_end integer,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_relation_evidence_kind_check CHECK (
                evidence_kind IN ('primary_text', 'official_metadata', 'deterministic_match', 'manual_review')
            ),
            CONSTRAINT legal_relation_evidence_presence_check CHECK (
                observation_id IS NOT NULL OR artifact_page_id IS NOT NULL
            ),
            CONSTRAINT legal_relation_evidence_offsets_check CHECK (
                (evidence_char_start IS NULL AND evidence_char_end IS NULL)
                OR (
                    evidence_char_start IS NOT NULL
                    AND evidence_char_end IS NOT NULL
                    AND evidence_char_start >= 0
                    AND evidence_char_end > evidence_char_start
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_relation_evidence_relation_idx "
        "ON corpus.legal_relation_evidence (relation_id)"
    )
    op.execute(
        "CREATE INDEX legal_relation_evidence_page_idx "
        "ON corpus.legal_relation_evidence (artifact_page_id) "
        "WHERE artifact_page_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_requirements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
                REFERENCES corpus.scopes(id),
            jurisdiction_code text NOT NULL,
            requirement_type text NOT NULL,
            canonical_text text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            effective_from date,
            effective_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_requirements_text_nonempty CHECK (btrim(canonical_text) <> ''),
            CONSTRAINT legal_requirements_status_check CHECK (
                status IN ('active', 'inactive', 'uncertain', 'superseded')
            ),
            CONSTRAINT legal_requirements_effective_range_check CHECK (
                effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
            ),
            CONSTRAINT legal_requirements_scope_id_id_key UNIQUE (scope_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_requirements_jurisdiction_status_idx "
        "ON corpus.legal_requirements (jurisdiction_code, status)"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_requirement_sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            requirement_id uuid NOT NULL REFERENCES corpus.legal_requirements(id) ON DELETE CASCADE,
            document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            provision_id uuid,
            source_role text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            evidence_excerpt text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_requirement_sources_role_check CHECK (
                source_role IN (
                    'establishes', 'defines', 'amends', 'repeals',
                    'creates_exception', 'interprets', 'satisfies', 'evidences'
                )
            ),
            CONSTRAINT legal_requirement_sources_status_check CHECK (
                verification_status IN ('candidate', 'verified', 'conflicting', 'rejected', 'superseded')
            ),
            CONSTRAINT legal_requirement_sources_provision_fkey
                FOREIGN KEY (document_id, provision_id)
                REFERENCES corpus.legal_document_provisions(document_id, id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT legal_requirement_sources_unique UNIQUE (
                requirement_id, document_id, provision_id, source_role
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_requirement_sources_requirement_idx "
        "ON corpus.legal_requirement_sources (requirement_id, verification_status)"
    )
    op.execute(
        "CREATE INDEX legal_requirement_sources_document_idx "
        "ON corpus.legal_requirement_sources (document_id, source_role)"
    )

    op.execute(
        """
        CREATE TABLE corpus.legal_tags (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug text NOT NULL UNIQUE,
            label text NOT NULL,
            tag_type text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_tags_slug_check CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
            CONSTRAINT legal_tags_type_check CHECK (
                tag_type IN ('topic', 'doctrine', 'practice_area', 'industry', 'procedure', 'institution', 'other')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_document_tags (
            document_id uuid NOT NULL REFERENCES corpus.legal_documents(id) ON DELETE CASCADE,
            tag_id uuid NOT NULL REFERENCES corpus.legal_tags(id) ON DELETE CASCADE,
            provenance text NOT NULL,
            confidence real,
            evidence_artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (document_id, tag_id, provenance),
            CONSTRAINT legal_document_tags_provenance_check CHECK (
                provenance IN ('source_provided', 'deterministic', 'agent_extracted', 'human_reviewed')
            ),
            CONSTRAINT legal_document_tags_confidence_check CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
            )
        )
        """
    )
    op.execute("CREATE INDEX legal_document_tags_tag_idx ON corpus.legal_document_tags (tag_id)")

    op.execute(
        """
        COMMENT ON TABLE corpus.legal_relation_observations IS
        'Evidence-bearing candidate legal relationships. Observations are never canonical merely because an LLM or parser emitted them.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_relations IS
        'Verified canonical directed legal relationships between documents or exact provisions.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_requirements IS
        'Canonical legal obligations or requirements that may be established, interpreted, amended, excepted, or satisfied by legal documents.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_document_tags IS
        'Classification metadata only. Tags describe subject or category and must not substitute for typed legal relations.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.legal_document_tags")
    op.execute("DROP TABLE IF EXISTS corpus.legal_tags")
    op.execute("DROP TABLE IF EXISTS corpus.legal_requirement_sources")
    op.execute("DROP TABLE IF EXISTS corpus.legal_requirements")
    op.execute("DROP TABLE IF EXISTS corpus.legal_relation_evidence")
    op.execute("DROP TABLE IF EXISTS corpus.legal_relations")
    op.execute("DROP TABLE IF EXISTS corpus.legal_relation_observations")
    op.execute("DROP TABLE IF EXISTS corpus.legal_document_provisions")
