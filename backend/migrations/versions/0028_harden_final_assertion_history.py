"""Harden scope and bitemporal history for final legal assertions.

Revision ID: 0028_harden_assertion_history
Revises: 0027_harden_final_model
Create Date: 2026-09-16
"""

from alembic import op

revision = "0028_harden_assert_history"
down_revision = "0027_harden_final_model"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # Norm assertions and their sources must share scope.
    op.execute(
        "ALTER TABLE corpus.legal_norm_assertions "
        "ADD CONSTRAINT legal_norm_assertions_scope_id_id_key UNIQUE (scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_norm_sources "
        "ADD COLUMN assertion_scope_id uuid NOT NULL "
        f"DEFAULT '{PUBLIC_SCOPE_ID}'::uuid"
    )
    op.execute(
        "UPDATE corpus.legal_norm_sources s SET assertion_scope_id = a.scope_id "
        "FROM corpus.legal_norm_assertions a WHERE a.id = s.norm_assertion_id"
    )
    op.execute(
        "ALTER TABLE corpus.legal_norm_sources "
        "ADD CONSTRAINT legal_norm_sources_same_scope_assertion_fkey "
        "FOREIGN KEY (assertion_scope_id, norm_assertion_id) "
        "REFERENCES corpus.legal_norm_assertions(scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_norm_sources "
        "ADD CONSTRAINT legal_norm_sources_scope_match_check "
        "CHECK (scope_id = assertion_scope_id)"
    )

    # Structural relation identity is scope-bound. Cross-tenant legal edges are
    # impossible even if a caller bypasses repository code.
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        f"ADD COLUMN scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid"
    )
    op.execute(
        """
        UPDATE corpus.legal_relation_identities r
        SET scope_id = d.scope_id
        FROM corpus.legal_documents d
        WHERE d.id = r.source_document_id
        """
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        "DROP CONSTRAINT legal_relation_identities_source_document_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        "DROP CONSTRAINT legal_relation_identities_target_document_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        "ADD CONSTRAINT legal_relation_identities_source_scope_fkey "
        "FOREIGN KEY (scope_id, source_document_id) "
        "REFERENCES corpus.legal_documents(scope_id, id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        "ADD CONSTRAINT legal_relation_identities_target_scope_fkey "
        "FOREIGN KEY (scope_id, target_document_id) "
        "REFERENCES corpus.legal_documents(scope_id, id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_identities "
        "ADD CONSTRAINT legal_relation_identities_scope_id_id_key UNIQUE (scope_id, id)"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_assertions "
        f"ADD COLUMN scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid"
    )
    op.execute(
        """
        UPDATE corpus.legal_relation_assertions a
        SET scope_id = r.scope_id
        FROM corpus.legal_relation_identities r
        WHERE r.id = a.relation_identity_id
        """
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_assertions "
        "DROP CONSTRAINT legal_relation_assertions_relation_identity_id_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.legal_relation_assertions "
        "ADD CONSTRAINT legal_relation_assertions_same_scope_identity_fkey "
        "FOREIGN KEY (scope_id, relation_identity_id) "
        "REFERENCES corpus.legal_relation_identities(scope_id, id) ON DELETE CASCADE"
    )

    # Serialize and reject overlapping system-knowledge intervals. This applies
    # to mutable assertions; propositions themselves remain immutable claims.
    _create_overlap_guard(
        table="legal_norm_assertions",
        key="proposition_id",
        function="reject_norm_knowledge_overlap",
        lock_seed=2801,
    )
    _create_overlap_guard(
        table="legal_relation_assertions",
        key="relation_identity_id",
        function="reject_relation_knowledge_overlap",
        lock_seed=2802,
    )
    _create_treatment_overlap_guard()
    _create_precedent_overlap_guard()
    _create_decision_status_overlap_guard()


def _create_overlap_guard(
    *,
    table: str,
    key: str,
    function: str,
    lock_seed: int,
) -> None:
    op.execute(
        f"""
        CREATE FUNCTION corpus.{function}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.{key}::text, {lock_seed})
            );
            IF EXISTS (
                SELECT 1 FROM corpus.{table} k
                WHERE k.{key} = NEW.{key}
                  AND k.id <> NEW.id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping knowledge interval in {table}'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_knowledge_overlap "
        f"BEFORE INSERT OR UPDATE ON corpus.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION corpus.{function}()"
    )


def _create_treatment_overlap_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.reject_treatment_knowledge_overlap() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.source_case_id, NEW.target_case_id,
                    NEW.treatment_type, NEW.issue_proposition_id,
                    NEW.source_proposition_id, NEW.target_proposition_id),
                2803
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.legal_treatment_assertions k
                WHERE k.id <> NEW.id
                  AND k.source_case_id = NEW.source_case_id
                  AND k.target_case_id = NEW.target_case_id
                  AND k.treatment_type = NEW.treatment_type
                  AND k.issue_proposition_id IS NOT DISTINCT FROM NEW.issue_proposition_id
                  AND k.source_proposition_id IS NOT DISTINCT FROM NEW.source_proposition_id
                  AND k.target_proposition_id IS NOT DISTINCT FROM NEW.target_proposition_id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping judicial treatment knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_treatment_assertions_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.legal_treatment_assertions "
        "FOR EACH ROW EXECUTE FUNCTION corpus.reject_treatment_knowledge_overlap()"
    )


def _create_precedent_overlap_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.reject_precedent_knowledge_overlap() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.decision_id, NEW.proposition_id,
                    NEW.authority_type, NEW.jurisdiction_code,
                    NEW.court_id, NEW.legal_matter_concept_id),
                2804
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.precedential_authority_assertions k
                WHERE k.id <> NEW.id
                  AND k.decision_id = NEW.decision_id
                  AND k.proposition_id IS NOT DISTINCT FROM NEW.proposition_id
                  AND k.authority_type = NEW.authority_type
                  AND k.jurisdiction_code IS NOT DISTINCT FROM NEW.jurisdiction_code
                  AND k.court_id IS NOT DISTINCT FROM NEW.court_id
                  AND k.legal_matter_concept_id IS NOT DISTINCT FROM NEW.legal_matter_concept_id
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping precedent knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER precedential_authority_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.precedential_authority_assertions "
        "FOR EACH ROW EXECUTE FUNCTION corpus.reject_precedent_knowledge_overlap()"
    )


def _create_decision_status_overlap_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.reject_decision_status_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.case_id, NEW.status_type, NEW.occurred_on),
                2805
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.decision_legal_status_events k
                WHERE k.id <> NEW.id
                  AND k.case_id = NEW.case_id
                  AND k.status_type = NEW.status_type
                  AND k.occurred_on IS NOT DISTINCT FROM NEW.occurred_on
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping decision-status knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER decision_legal_status_no_knowledge_overlap "
        "BEFORE INSERT OR UPDATE ON corpus.decision_legal_status_events "
        "FOR EACH ROW EXECUTE FUNCTION corpus.reject_decision_status_knowledge_overlap()"
    )


def downgrade() -> None:
    raise RuntimeError("0028 is part of the pre-ingestion normalization boundary")
