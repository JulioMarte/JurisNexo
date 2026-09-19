"""Add first-class legal issues and factual propositions.

Revision ID: 0043_issues_facts
Revises: 0042_concept_foundation
Create Date: 2026-09-17

A procedural claim, a legal question, a party allegation, a judicial factual
finding and a legal proposition are different objects. This migration gives
issues and factual propositions canonical identities with evidence and typed
subject relations while preserving their epistemic status.
"""

from alembic import op

revision = "0043_issues_facts"
down_revision = "0042_concept_foundation"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
STATUS = "'candidate','verified','conflicting','rejected','superseded'"
ASSERTION_KIND = (
    "'explicit_primary_text','derived_from_primary_text',"
    "'synthesized_interpretation','human_authored'"
)


def upgrade() -> None:
    _legal_issues()
    _factual_propositions()
    _verified_requires_evidence()


def _legal_issues() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.legal_issues (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            canonical_question text NOT NULL,
            normalized_question text,
            assertion_kind text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            extraction_confidence real,
            semantic_confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_issues_question_nonempty
                CHECK (btrim(canonical_question) <> ''),
            CONSTRAINT legal_issues_assertion_kind_check
                CHECK (assertion_kind IN ({ASSERTION_KIND})),
            CONSTRAINT legal_issues_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT legal_issues_extraction_confidence_check CHECK (
                extraction_confidence IS NULL OR
                (extraction_confidence >= 0 AND extraction_confidence <= 1)
            ),
            CONSTRAINT legal_issues_semantic_confidence_check CHECK (
                semantic_confidence IS NULL OR
                (semantic_confidence >= 0 AND semantic_confidence <= 1)
            ),
            CONSTRAINT legal_issues_scope_id_id_key UNIQUE (scope_id,id)
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_issues_scope_status_idx "
        "ON corpus.legal_issues(scope_id,verification_status,created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.reject_legal_issue_identity_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.canonical_question IS DISTINCT FROM OLD.canonical_question
               OR NEW.normalized_question IS DISTINCT FROM OLD.normalized_question
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION
                    'legal issue identity is immutable; supersede it with a new issue'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER legal_issues_immutable_identity "
        "BEFORE UPDATE ON corpus.legal_issues FOR EACH ROW "
        "EXECUTE FUNCTION corpus.reject_legal_issue_identity_mutation()"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.legal_issue_subjects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            issue_id uuid NOT NULL,
            relation_scheme_code text NOT NULL DEFAULT 'legal_issue_relation',
            relation_concept_id uuid NOT NULL,
            subject_type text NOT NULL,
            judicial_decision_id uuid,
            proceeding_id uuid,
            claim_id uuid,
            proposition_id uuid,
            ordinal integer,
            raw_relation text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_issue_subjects_scheme_check
                CHECK (relation_scheme_code='legal_issue_relation'),
            CONSTRAINT legal_issue_subjects_type_check CHECK (
                subject_type IN ('judicial_decision','proceeding','claim','proposition')
            ),
            CONSTRAINT legal_issue_subjects_shape_check CHECK (
                (subject_type='judicial_decision' AND judicial_decision_id IS NOT NULL
                    AND proceeding_id IS NULL AND claim_id IS NULL AND proposition_id IS NULL)
                OR
                (subject_type='proceeding' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NOT NULL AND claim_id IS NULL AND proposition_id IS NULL)
                OR
                (subject_type='claim' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NULL AND claim_id IS NOT NULL AND proposition_id IS NULL)
                OR
                (subject_type='proposition' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NULL AND claim_id IS NULL AND proposition_id IS NOT NULL)
            ),
            CONSTRAINT legal_issue_subjects_ordinal_check
                CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT legal_issue_subjects_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT legal_issue_subjects_issue_fkey
                FOREIGN KEY (scope_id,issue_id)
                REFERENCES corpus.legal_issues(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT legal_issue_subjects_relation_fkey
                FOREIGN KEY (relation_scheme_code,relation_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT legal_issue_subjects_decision_fkey
                FOREIGN KEY (scope_id,judicial_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id,id),
            CONSTRAINT legal_issue_subjects_proceeding_fkey
                FOREIGN KEY (scope_id,proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id,id),
            CONSTRAINT legal_issue_subjects_claim_fkey
                FOREIGN KEY (scope_id,claim_id)
                REFERENCES corpus.legal_claims(scope_id,id),
            CONSTRAINT legal_issue_subjects_proposition_fkey
                FOREIGN KEY (scope_id,proposition_id)
                REFERENCES corpus.legal_propositions(scope_id,id)
        )
        """
    )
    for subject_type, column in (
        ("judicial_decision", "judicial_decision_id"),
        ("proceeding", "proceeding_id"),
        ("claim", "claim_id"),
        ("proposition", "proposition_id"),
    ):
        op.execute(
            f"CREATE UNIQUE INDEX legal_issue_subjects_{subject_type}_key "
            f"ON corpus.legal_issue_subjects(issue_id,relation_concept_id,{column}) "
            f"WHERE subject_type='{subject_type}'"
        )
    op.execute(
        "CREATE INDEX legal_issue_subjects_issue_idx "
        "ON corpus.legal_issue_subjects(scope_id,issue_id,ordinal)"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.legal_issue_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            issue_id uuid NOT NULL,
            source_decision_id uuid,
            source_document_id uuid,
            case_page_id uuid,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            exact_excerpt text,
            char_start integer,
            char_end integer,
            extraction_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_issue_evidence_presence_check CHECK (
                source_decision_id IS NOT NULL OR source_document_id IS NOT NULL
                OR artifact_page_id IS NOT NULL
            ),
            CONSTRAINT legal_issue_evidence_page_requires_decision CHECK (
                case_page_id IS NULL OR source_decision_id IS NOT NULL
            ),
            CONSTRAINT legal_issue_evidence_offsets_check CHECK (
                (char_start IS NULL AND char_end IS NULL)
                OR (char_start IS NOT NULL AND char_end IS NOT NULL
                    AND char_start >= 0 AND char_end > char_start)
            ),
            CONSTRAINT legal_issue_evidence_issue_fkey
                FOREIGN KEY (scope_id,issue_id)
                REFERENCES corpus.legal_issues(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT legal_issue_evidence_decision_fkey
                FOREIGN KEY (scope_id,source_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id,id),
            CONSTRAINT legal_issue_evidence_document_fkey
                FOREIGN KEY (scope_id,source_document_id)
                REFERENCES corpus.legal_documents(scope_id,id),
            CONSTRAINT legal_issue_evidence_case_page_fkey
                FOREIGN KEY (source_decision_id,case_page_id)
                REFERENCES corpus.case_pages(case_id,id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_issue_evidence_issue_idx "
        "ON corpus.legal_issue_evidence(scope_id,issue_id)"
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_issues IS
        'Canonical legal questions/issues. An issue is not a claim, holding or topic tag. Its wording is immutable; competing formulations coexist until resolved rather than being silently rewritten.'
        """
    )


def _factual_propositions() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.factual_propositions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid
                REFERENCES corpus.scopes(id),
            kind_scheme_code text NOT NULL DEFAULT 'factual_proposition_kind',
            kind_concept_id uuid NOT NULL,
            canonical_text text NOT NULL,
            normalized_text text,
            assertion_kind text NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            extraction_confidence real,
            semantic_confidence real,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT factual_propositions_kind_scheme_check
                CHECK (kind_scheme_code='factual_proposition_kind'),
            CONSTRAINT factual_propositions_kind_fkey
                FOREIGN KEY (kind_scheme_code,kind_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT factual_propositions_text_nonempty
                CHECK (btrim(canonical_text) <> ''),
            CONSTRAINT factual_propositions_assertion_kind_check
                CHECK (assertion_kind IN ({ASSERTION_KIND})),
            CONSTRAINT factual_propositions_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT factual_propositions_extraction_confidence_check CHECK (
                extraction_confidence IS NULL OR
                (extraction_confidence >= 0 AND extraction_confidence <= 1)
            ),
            CONSTRAINT factual_propositions_semantic_confidence_check CHECK (
                semantic_confidence IS NULL OR
                (semantic_confidence >= 0 AND semantic_confidence <= 1)
            ),
            CONSTRAINT factual_propositions_scope_id_id_key UNIQUE (scope_id,id)
        )
        """
    )
    op.execute(
        "CREATE INDEX factual_propositions_scope_kind_idx "
        "ON corpus.factual_propositions(scope_id,kind_concept_id,verification_status)"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.reject_factual_proposition_identity_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.kind_concept_id IS DISTINCT FROM OLD.kind_concept_id
               OR NEW.canonical_text IS DISTINCT FROM OLD.canonical_text
               OR NEW.normalized_text IS DISTINCT FROM OLD.normalized_text
               OR NEW.assertion_kind IS DISTINCT FROM OLD.assertion_kind THEN
                RAISE EXCEPTION
                    'factual proposition identity is immutable; supersede it with a new proposition'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER factual_propositions_immutable_identity "
        "BEFORE UPDATE ON corpus.factual_propositions FOR EACH ROW "
        "EXECUTE FUNCTION corpus.reject_factual_proposition_identity_mutation()"
    )
    op.execute(
        f"""
        CREATE TABLE corpus.factual_proposition_subjects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            factual_proposition_id uuid NOT NULL,
            relation_scheme_code text NOT NULL DEFAULT 'factual_subject_relation',
            relation_concept_id uuid NOT NULL,
            subject_type text NOT NULL,
            judicial_decision_id uuid,
            proceeding_id uuid,
            claim_id uuid,
            party_role_id uuid,
            ordinal integer,
            raw_relation text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT factual_subjects_scheme_check
                CHECK (relation_scheme_code='factual_subject_relation'),
            CONSTRAINT factual_subjects_type_check CHECK (
                subject_type IN ('judicial_decision','proceeding','claim','party_role')
            ),
            CONSTRAINT factual_subjects_shape_check CHECK (
                (subject_type='judicial_decision' AND judicial_decision_id IS NOT NULL
                    AND proceeding_id IS NULL AND claim_id IS NULL AND party_role_id IS NULL)
                OR
                (subject_type='proceeding' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NOT NULL AND claim_id IS NULL AND party_role_id IS NULL)
                OR
                (subject_type='claim' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NULL AND claim_id IS NOT NULL AND party_role_id IS NULL)
                OR
                (subject_type='party_role' AND judicial_decision_id IS NULL
                    AND proceeding_id IS NULL AND claim_id IS NULL AND party_role_id IS NOT NULL)
            ),
            CONSTRAINT factual_subjects_ordinal_check
                CHECK (ordinal IS NULL OR ordinal > 0),
            CONSTRAINT factual_subjects_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT factual_subjects_fact_fkey
                FOREIGN KEY (scope_id,factual_proposition_id)
                REFERENCES corpus.factual_propositions(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT factual_subjects_relation_fkey
                FOREIGN KEY (relation_scheme_code,relation_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT factual_subjects_decision_fkey
                FOREIGN KEY (scope_id,judicial_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id,id),
            CONSTRAINT factual_subjects_proceeding_fkey
                FOREIGN KEY (scope_id,proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id,id),
            CONSTRAINT factual_subjects_claim_fkey
                FOREIGN KEY (scope_id,claim_id)
                REFERENCES corpus.legal_claims(scope_id,id),
            CONSTRAINT factual_subjects_party_role_fkey
                FOREIGN KEY (scope_id,party_role_id)
                REFERENCES corpus.proceeding_party_roles(scope_id,id)
        )
        """
    )
    for subject_type, column in (
        ("judicial_decision", "judicial_decision_id"),
        ("proceeding", "proceeding_id"),
        ("claim", "claim_id"),
        ("party_role", "party_role_id"),
    ):
        op.execute(
            f"CREATE UNIQUE INDEX factual_subjects_{subject_type}_key "
            f"ON corpus.factual_proposition_subjects(factual_proposition_id,relation_concept_id,{column}) "
            f"WHERE subject_type='{subject_type}'"
        )
    op.execute(
        f"""
        CREATE TABLE corpus.factual_proposition_evidence (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            factual_proposition_id uuid NOT NULL,
            source_decision_id uuid,
            source_document_id uuid,
            case_page_id uuid,
            artifact_page_id uuid REFERENCES corpus.artifact_pages(id),
            exact_excerpt text,
            char_start integer,
            char_end integer,
            extraction_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT factual_evidence_presence_check CHECK (
                source_decision_id IS NOT NULL OR source_document_id IS NOT NULL
                OR artifact_page_id IS NOT NULL
            ),
            CONSTRAINT factual_evidence_page_requires_decision CHECK (
                case_page_id IS NULL OR source_decision_id IS NOT NULL
            ),
            CONSTRAINT factual_evidence_offsets_check CHECK (
                (char_start IS NULL AND char_end IS NULL)
                OR (char_start IS NOT NULL AND char_end IS NOT NULL
                    AND char_start >= 0 AND char_end > char_start)
            ),
            CONSTRAINT factual_evidence_fact_fkey
                FOREIGN KEY (scope_id,factual_proposition_id)
                REFERENCES corpus.factual_propositions(scope_id,id) ON DELETE CASCADE,
            CONSTRAINT factual_evidence_decision_fkey
                FOREIGN KEY (scope_id,source_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id,id),
            CONSTRAINT factual_evidence_document_fkey
                FOREIGN KEY (scope_id,source_document_id)
                REFERENCES corpus.legal_documents(scope_id,id),
            CONSTRAINT factual_evidence_case_page_fkey
                FOREIGN KEY (source_decision_id,case_page_id)
                REFERENCES corpus.case_pages(case_id,id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    op.execute(
        "CREATE INDEX factual_proposition_evidence_fact_idx "
        "ON corpus.factual_proposition_evidence(scope_id,factual_proposition_id)"
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.factual_propositions IS
        'Canonical factual propositions. Kind distinguishes allegation, admission, finding and other epistemic/legal roles; storing an allegation never implies the alleged fact is true.'
        """
    )


def _verified_requires_evidence() -> None:
    op.execute(
        """
        CREATE FUNCTION corpus.require_verified_issue_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.legal_issue_evidence e
                   WHERE e.issue_id=NEW.id AND e.scope_id=NEW.scope_id
               )
               AND NEW.verification_method NOT IN ('human_legal_analysis','administrative_resolution') THEN
                RAISE EXCEPTION
                    'verified legal issue requires evidence or explicit human/administrative verification'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER legal_issues_verified_require_evidence "
        "AFTER INSERT OR UPDATE OF verification_status,verification_method "
        "ON corpus.legal_issues DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION corpus.require_verified_issue_evidence()"
    )
    op.execute(
        """
        CREATE FUNCTION corpus.require_verified_fact_evidence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.verification_status='verified'
               AND NOT EXISTS (
                   SELECT 1 FROM corpus.factual_proposition_evidence e
                   WHERE e.factual_proposition_id=NEW.id AND e.scope_id=NEW.scope_id
               )
               AND NEW.verification_method NOT IN ('human_legal_analysis','administrative_resolution') THEN
                RAISE EXCEPTION
                    'verified factual proposition requires evidence or explicit human/administrative verification'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER factual_propositions_verified_require_evidence "
        "AFTER INSERT OR UPDATE OF verification_status,verification_method "
        "ON corpus.factual_propositions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION corpus.require_verified_fact_evidence()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0043 creates canonical V4 legal issue and factual-proposition identities"
    )
