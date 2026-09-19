"""Harden V4 semantic boundaries.

Revision ID: 0046_v4_hardening
Revises: 0045_entity_resolution
Create Date: 2026-09-17

Restores procedural-context checks after disposition targets become arguments,
prevents new issue/fact truth from being duplicated in legal_propositions,
requires source evidence for verified interpretive identities, and keeps the
shared concept hierarchy acyclic.
"""

from alembic import op

revision = "0046_v4_hardening"
down_revision = "0045_entity_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _remove_duplicate_proposition_kinds()
    _harden_verified_evidence()
    _harden_action_argument_context()
    _harden_argument_uniqueness()
    _harden_entity_assertion_evidence()
    _harden_concept_hierarchy()


def _remove_duplicate_proposition_kinds() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM corpus.legal_propositions
                WHERE proposition_type IN ('issue','material_fact','procedural_fact')
            ) THEN
                RAISE EXCEPTION
                    'V4 cannot remove duplicate proposition categories while issue/fact proposition rows exist; migrate them explicitly first';
            END IF;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE corpus.legal_propositions "
        "DROP CONSTRAINT legal_propositions_type_check"
    )
    op.execute(
        """
        ALTER TABLE corpus.legal_propositions
        ADD CONSTRAINT legal_propositions_type_check CHECK (
            proposition_type IN (
                'holding','legal_rule','legal_test','legal_requirement','exception',
                'argument','counterargument','reasoning','conclusion','dictum','other'
            )
        )
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_propositions IS
        'Immutable legal/argumentative proposition identity. Legal questions belong in legal_issues; allegations and judicial factual findings belong in factual_propositions; these identities must not be duplicated here.'
        """
    )


def _harden_verified_evidence() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.require_verified_issue_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.legal_issue_evidence e
                   WHERE e.issue_id=NEW.id
                     AND e.scope_id=NEW.scope_id
                     AND (
                         e.case_page_id IS NOT NULL
                         OR e.artifact_page_id IS NOT NULL
                         OR btrim(coalesce(e.exact_excerpt,'')) <> ''
                     )
               ) THEN
                RAISE EXCEPTION
                    'verified legal issue requires page/passage or exact-excerpt evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION corpus.require_verified_fact_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.factual_proposition_evidence e
                   WHERE e.factual_proposition_id=NEW.id
                     AND e.scope_id=NEW.scope_id
                     AND (
                         e.case_page_id IS NOT NULL
                         OR e.artifact_page_id IS NOT NULL
                         OR btrim(coalesce(e.exact_excerpt,'')) <> ''
                     )
               ) THEN
                RAISE EXCEPTION
                    'verified factual proposition requires page/passage or exact-excerpt evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )


def _harden_action_argument_context() -> None:
    op.execute("DROP FUNCTION IF EXISTS corpus.validate_disposition_target()")
    op.execute(
        """
        CREATE FUNCTION corpus.validate_disposition_action_argument_context()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_decision uuid;
        DECLARE target_proceeding uuid;
        BEGIN
            SELECT case_id INTO source_decision
            FROM corpus.judicial_decision_dispositions
            WHERE id=NEW.disposition_id AND scope_id=NEW.scope_id;
            IF source_decision IS NULL THEN
                RAISE EXCEPTION 'unknown or cross-scope judicial disposition'
                    USING ERRCODE='23503';
            END IF;

            IF NEW.object_type='claim' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.legal_claims
                WHERE id=NEW.target_claim_id AND scope_id=NEW.scope_id;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition action cannot use a claim from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.object_type='party_role' THEN
                SELECT proceeding_id INTO target_proceeding
                FROM corpus.proceeding_party_roles
                WHERE id=NEW.target_party_role_id AND scope_id=NEW.scope_id;
                IF target_proceeding IS NULL OR NOT EXISTS (
                    SELECT 1 FROM corpus.proceeding_decisions pd
                    WHERE pd.scope_id=NEW.scope_id
                      AND pd.proceeding_id=target_proceeding
                      AND pd.case_id=source_decision
                      AND pd.verification_status NOT IN ('rejected','superseded')
                ) THEN
                    RAISE EXCEPTION
                        'disposition action cannot use a party role from an unrelated proceeding'
                        USING ERRCODE='23514';
                END IF;
            ELSIF NEW.object_type='proposition' THEN
                IF EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                ) AND NOT EXISTS (
                    SELECT 1 FROM corpus.legal_proposition_subjects s
                    WHERE s.scope_id=NEW.scope_id
                      AND s.proposition_id=NEW.target_proposition_id
                      AND s.subject_type='judicial_decision'
                      AND s.judicial_decision_id=source_decision
                ) THEN
                    RAISE EXCEPTION
                        'disposition action proposition belongs to another decision'
                        USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER disposition_arguments_validate_context "
        "BEFORE INSERT OR UPDATE ON corpus.judicial_disposition_action_arguments "
        "FOR EACH ROW EXECUTE FUNCTION corpus.validate_disposition_action_argument_context()"
    )


def _harden_argument_uniqueness() -> None:
    for object_type, column in (
        ("claim", "target_claim_id"),
        ("party_role", "target_party_role_id"),
        ("proceeding", "target_proceeding_id"),
        ("decision", "target_decision_id"),
        ("proposition", "target_proposition_id"),
        ("provision", "target_provision_id"),
        ("court", "target_court_id"),
        ("court_organ", "target_court_organ_id"),
    ):
        op.execute(
            f"CREATE UNIQUE INDEX disposition_arguments_{object_type}_key "
            f"ON corpus.judicial_disposition_action_arguments(action_id,role_concept_id,{column}) "
            f"WHERE object_type='{object_type}'"
        )


def _harden_entity_assertion_evidence() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.require_verified_entity_identity_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.entity_identity_assertion_evidence e
                   WHERE e.assertion_id=NEW.id AND e.scope_id=NEW.scope_id
               ) THEN
                RAISE EXCEPTION
                    'verified entity identity assertion requires persisted evidence'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER entity_identity_verified_require_evidence "
        "AFTER INSERT OR UPDATE OF verification_status ON corpus.entity_identity_assertions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION corpus.require_verified_entity_identity_evidence()"
    )


def _harden_concept_hierarchy() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.reject_legal_concept_hierarchy_cycle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE normalized_source uuid;
        DECLARE normalized_target uuid;
        BEGIN
            IF NEW.relation_type NOT IN ('broader','narrower') THEN
                RETURN NEW;
            END IF;

            IF NEW.relation_type='broader' THEN
                normalized_source := NEW.source_concept_id;
                normalized_target := NEW.target_concept_id;
            ELSE
                normalized_source := NEW.target_concept_id;
                normalized_target := NEW.source_concept_id;
            END IF;

            IF EXISTS (
                WITH RECURSIVE walk(id) AS (
                    SELECT normalized_target
                    UNION
                    SELECT CASE
                        WHEN e.relation_type='broader' THEN e.target_concept_id
                        ELSE e.source_concept_id
                    END
                    FROM corpus.legal_concept_edges e
                    JOIN walk w ON (
                        (e.relation_type='broader' AND e.source_concept_id=w.id)
                        OR (e.relation_type='narrower' AND e.target_concept_id=w.id)
                    )
                    WHERE e.id<>NEW.id
                )
                SELECT 1 FROM walk WHERE id=normalized_source
            ) THEN
                RAISE EXCEPTION 'legal concept hierarchy cycle detected'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_concept_edges_reject_hierarchy_cycle "
        "BEFORE INSERT OR UPDATE ON corpus.legal_concept_edges FOR EACH ROW "
        "EXECUTE FUNCTION corpus.reject_legal_concept_hierarchy_cycle()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0046 hardens canonical V4 invariants and is intentionally non-destructive"
    )
