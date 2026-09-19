"""Add auditable entity-identity assertions and resolutions.

Revision ID: 0045_entity_resolution
Revises: 0044_action_arguments
Create Date: 2026-09-17

Name similarity is evidence, not identity. V4 preserves observed legal entities
and records identity claims, evidence and bitemporal canonical resolutions
without deleting or rewriting the observed entity.
"""

from alembic import op

revision = "0045_entity_resolution"
down_revision = "0044_action_arguments"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
STATUS = "'candidate','verified','conflicting','rejected','superseded'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.entity_identity_assertions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            observed_entity_id uuid NOT NULL,
            candidate_entity_id uuid NOT NULL,
            relation_scheme_code text NOT NULL DEFAULT 'entity_identity_relation',
            relation_concept_id uuid NOT NULL,
            known_from timestamptz NOT NULL DEFAULT now(),
            known_to timestamptz,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            extraction_confidence real,
            semantic_confidence real,
            evidence_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_identity_assertions_distinct_check
                CHECK (observed_entity_id <> candidate_entity_id),
            CONSTRAINT entity_identity_assertions_scheme_check
                CHECK (relation_scheme_code='entity_identity_relation'),
            CONSTRAINT entity_identity_assertions_relation_fkey
                FOREIGN KEY (relation_scheme_code,relation_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT entity_identity_assertions_known_range_check
                CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT entity_identity_assertions_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT entity_identity_assertions_extraction_confidence_check CHECK (
                extraction_confidence IS NULL OR
                (extraction_confidence >= 0 AND extraction_confidence <= 1)
            ),
            CONSTRAINT entity_identity_assertions_semantic_confidence_check CHECK (
                semantic_confidence IS NULL OR
                (semantic_confidence >= 0 AND semantic_confidence <= 1)
            ),
            CONSTRAINT entity_identity_assertions_observed_fkey
                FOREIGN KEY (scope_id,observed_entity_id)
                REFERENCES corpus.legal_entities(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT entity_identity_assertions_candidate_fkey
                FOREIGN KEY (scope_id,candidate_entity_id)
                REFERENCES corpus.legal_entities(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT entity_identity_assertions_history_key UNIQUE (
                observed_entity_id,candidate_entity_id,relation_concept_id,known_from
            ),
            CONSTRAINT entity_identity_assertions_scope_id_id_key UNIQUE (scope_id,id)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_identity_assertions_observed_idx "
        "ON corpus.entity_identity_assertions(scope_id,observed_entity_id,known_from DESC)"
    )
    op.execute(
        "CREATE INDEX entity_identity_assertions_candidate_idx "
        "ON corpus.entity_identity_assertions(scope_id,candidate_entity_id,known_from DESC)"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.entity_identity_assertion_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            assertion_id uuid NOT NULL,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            source_document_observation_id uuid
                REFERENCES corpus.source_document_observations(id) ON DELETE SET NULL,
            exact_excerpt text,
            char_start integer,
            char_end integer,
            evidence_kind text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_identity_evidence_presence_check CHECK (
                artifact_page_id IS NOT NULL OR source_document_observation_id IS NOT NULL
            ),
            CONSTRAINT entity_identity_evidence_kind_check CHECK (
                evidence_kind IN (
                    'primary_text','official_metadata','deterministic_match','manual_review'
                )
            ),
            CONSTRAINT entity_identity_evidence_offsets_check CHECK (
                (char_start IS NULL AND char_end IS NULL)
                OR (char_start IS NOT NULL AND char_end IS NOT NULL
                    AND char_start >= 0 AND char_end > char_start)
            ),
            CONSTRAINT entity_identity_evidence_assertion_fkey
                FOREIGN KEY (scope_id,assertion_id)
                REFERENCES corpus.entity_identity_assertions(scope_id,id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_identity_evidence_assertion_idx "
        "ON corpus.entity_identity_assertion_evidence(scope_id,assertion_id)"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.entity_identity_resolutions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            observed_entity_id uuid NOT NULL,
            canonical_entity_id uuid NOT NULL,
            supporting_assertion_id uuid NOT NULL,
            known_from timestamptz NOT NULL DEFAULT now(),
            known_to timestamptz,
            verification_status text NOT NULL DEFAULT 'verified',
            verification_method text NOT NULL,
            review_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_identity_resolutions_distinct_check
                CHECK (observed_entity_id <> canonical_entity_id),
            CONSTRAINT entity_identity_resolutions_known_range_check
                CHECK (known_to IS NULL OR known_to > known_from),
            CONSTRAINT entity_identity_resolutions_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT entity_identity_resolutions_observed_fkey
                FOREIGN KEY (scope_id,observed_entity_id)
                REFERENCES corpus.legal_entities(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT entity_identity_resolutions_canonical_fkey
                FOREIGN KEY (scope_id,canonical_entity_id)
                REFERENCES corpus.legal_entities(scope_id,id),
            CONSTRAINT entity_identity_resolutions_assertion_fkey
                FOREIGN KEY (scope_id,supporting_assertion_id)
                REFERENCES corpus.entity_identity_assertions(scope_id,id),
            CONSTRAINT entity_identity_resolutions_history_key UNIQUE (
                observed_entity_id,known_from
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX entity_identity_resolutions_current_idx "
        "ON corpus.entity_identity_resolutions(observed_entity_id) "
        "WHERE known_to IS NULL AND verification_status NOT IN ('rejected','superseded')"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.validate_entity_identity_resolution()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE assertion_relation text;
        BEGIN
            SELECT c.code INTO assertion_relation
            FROM corpus.entity_identity_assertions a
            JOIN corpus.legal_concepts c ON c.id=a.relation_concept_id
            WHERE a.id=NEW.supporting_assertion_id
              AND a.scope_id=NEW.scope_id
              AND a.observed_entity_id=NEW.observed_entity_id
              AND a.candidate_entity_id=NEW.canonical_entity_id
              AND a.verification_status='verified';

            IF assertion_relation IS NULL OR assertion_relation NOT IN (
                'same_as','merged_into'
            ) THEN
                RAISE EXCEPTION
                    'entity identity resolution requires a matching verified conclusive identity assertion'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_identity_resolutions_validate_assertion "
        "BEFORE INSERT OR UPDATE OF scope_id,observed_entity_id,canonical_entity_id,supporting_assertion_id "
        "ON corpus.entity_identity_resolutions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.validate_entity_identity_resolution()"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.reject_entity_resolution_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.observed_entity_id::text,4501)
            );
            IF NEW.verification_status NOT IN ('rejected','superseded')
               AND EXISTS (
                   SELECT 1 FROM corpus.entity_identity_resolutions r
                   WHERE r.id<>NEW.id
                     AND r.observed_entity_id=NEW.observed_entity_id
                     AND r.verification_status NOT IN ('rejected','superseded')
                     AND tstzrange(r.known_from,r.known_to,'[)')
                         && tstzrange(NEW.known_from,NEW.known_to,'[)')
               ) THEN
                RAISE EXCEPTION
                    'overlapping canonical entity resolution knowledge interval'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_identity_resolutions_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.entity_identity_resolutions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.reject_entity_resolution_knowledge_overlap()"
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.entity_identity_assertions IS
        'Auditable claim that two preserved legal-entity identities denote the same, probably same, or different real-world entity. Similar names alone never perform a destructive merge.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.entity_identity_resolutions IS
        'Bitemporal resolution from an observed legal entity to the currently accepted canonical identity. A resolution requires a conclusive verified same_as/merged_into assertion; probable_same_as may remain evidence/candidate knowledge but cannot canonicalize identity. The observed entity remains addressable.'
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN corpus.legal_entities.identity_status IS
        'Coarse workflow summary only. Canonical cross-entity identity decisions live in entity_identity_assertions and entity_identity_resolutions.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0045 establishes auditable entity identity history and must not be destructively downgraded"
    )
