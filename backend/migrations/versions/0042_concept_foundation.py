"""Add the shared legal concept foundation for new V4 semantics.

Revision ID: 0042_concept_foundation
Revises: 0041_harden_disposition_targets
Create Date: 2026-09-17

This does not rewrite mature specialized concept registries. It establishes the
shared ontology substrate for new cross-jurisdiction semantic categories so
JurisNexo stops creating one physical *_concepts table for every new category.
"""

from alembic import op

revision = "0042_concept_foundation"
down_revision = "0041_harden_disposition_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE corpus.concept_schemes (
            code text PRIMARY KEY,
            name text NOT NULL,
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT concept_schemes_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT concept_schemes_name_nonempty CHECK (btrim(name) <> '')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scheme_code text NOT NULL REFERENCES corpus.concept_schemes(code),
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            code text NOT NULL,
            name text NOT NULL,
            description text,
            valid_from date,
            valid_to date,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_concepts_code_check
                CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT legal_concepts_name_nonempty CHECK (btrim(name) <> ''),
            CONSTRAINT legal_concepts_valid_range_check CHECK (
                valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
            ),
            CONSTRAINT legal_concepts_metadata_object_check
                CHECK (jsonb_typeof(metadata) = 'object'),
            CONSTRAINT legal_concepts_scheme_id_key UNIQUE (scheme_code, id),
            CONSTRAINT legal_concepts_identity_key UNIQUE NULLS NOT DISTINCT (
                scheme_code, jurisdiction_code, code
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_concepts_scheme_lookup_idx "
        "ON corpus.legal_concepts(scheme_code,jurisdiction_code,code)"
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_concept_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            concept_id uuid NOT NULL REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE,
            alias text NOT NULL,
            normalized_alias text,
            language_code text,
            source_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_concept_aliases_alias_nonempty CHECK (btrim(alias) <> ''),
            CONSTRAINT legal_concept_aliases_language_check CHECK (
                language_code IS NULL OR language_code ~ '^[a-z]{2,3}(-[A-Z]{2})?$'
            ),
            CONSTRAINT legal_concept_aliases_unique UNIQUE NULLS NOT DISTINCT (
                concept_id, language_code, alias
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_concept_aliases_lookup_idx "
        "ON corpus.legal_concept_aliases(normalized_alias) "
        "WHERE normalized_alias IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE corpus.legal_concept_edges (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_concept_id uuid NOT NULL REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE,
            relation_type text NOT NULL,
            target_concept_id uuid NOT NULL REFERENCES corpus.legal_concepts(id) ON DELETE CASCADE,
            valid_from date,
            valid_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT legal_concept_edges_distinct_check
                CHECK (source_concept_id <> target_concept_id),
            CONSTRAINT legal_concept_edges_relation_check CHECK (
                relation_type IN (
                    'broader', 'narrower', 'equivalent', 'close_match',
                    'related', 'historical_successor', 'derived_from'
                )
            ),
            CONSTRAINT legal_concept_edges_valid_range_check CHECK (
                valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
            ),
            CONSTRAINT legal_concept_edges_unique UNIQUE NULLS NOT DISTINCT (
                source_concept_id, relation_type, target_concept_id, valid_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX legal_concept_edges_source_idx "
        "ON corpus.legal_concept_edges(source_concept_id,relation_type)"
    )
    op.execute(
        "CREATE INDEX legal_concept_edges_target_idx "
        "ON corpus.legal_concept_edges(target_concept_id,relation_type)"
    )

    op.execute(
        """
        INSERT INTO corpus.concept_schemes(code,name,description) VALUES
        ('legal_issue_relation','Legal issue relation','How a persisted legal object relates to a legal issue/question.'),
        ('factual_proposition_kind','Factual proposition kind','Epistemic/legal role of a factual proposition without asserting that it is true.'),
        ('factual_subject_relation','Factual subject relation','How a decision, proceeding, claim or party role relates to a factual proposition.'),
        ('disposition_argument_role','Disposition action argument role','Semantic role played by an argument of a normalized dispositive action.'),
        ('entity_identity_relation','Entity identity relation','Claim about whether two observed legal entities denote the same real-world identity.')
        """
    )
    op.execute(
        """
        INSERT INTO corpus.legal_concepts(scheme_code,code,name) VALUES
        ('legal_issue_relation','addresses','Addresses'),
        ('legal_issue_relation','raises','Raises'),
        ('legal_issue_relation','answers','Answers'),
        ('legal_issue_relation','qualifies','Qualifies'),
        ('legal_issue_relation','rejects','Rejects'),
        ('legal_issue_relation','frames','Frames'),
        ('legal_issue_relation','supports','Supports'),
        ('legal_issue_relation','opposes','Opposes'),
        ('legal_issue_relation','related_to','Related to'),

        ('factual_proposition_kind','allegation','Allegation'),
        ('factual_proposition_kind','denial','Denial'),
        ('factual_proposition_kind','admission','Admission'),
        ('factual_proposition_kind','stipulation','Stipulation'),
        ('factual_proposition_kind','finding','Judicial finding'),
        ('factual_proposition_kind','presumption','Presumption'),
        ('factual_proposition_kind','background_fact','Background fact'),
        ('factual_proposition_kind','evidentiary_fact','Evidentiary fact'),

        ('factual_subject_relation','alleged_by','Alleged by'),
        ('factual_subject_relation','denied_by','Denied by'),
        ('factual_subject_relation','admitted_by','Admitted by'),
        ('factual_subject_relation','stipulated_by','Stipulated by'),
        ('factual_subject_relation','found_by','Found by judicial decision'),
        ('factual_subject_relation','supports_claim','Supports claim'),
        ('factual_subject_relation','opposes_claim','Opposes claim'),
        ('factual_subject_relation','material_to','Material to'),
        ('factual_subject_relation','occurred_in','Occurred in proceeding'),
        ('factual_subject_relation','mentioned_by','Mentioned by'),

        ('disposition_argument_role','object','Object'),
        ('disposition_argument_role','obligor','Obligor'),
        ('disposition_argument_role','beneficiary','Beneficiary'),
        ('disposition_argument_role','destination','Destination'),
        ('disposition_argument_role','claim','Claim'),
        ('disposition_argument_role','legal_provision','Legal provision'),
        ('disposition_argument_role','amount','Amount'),
        ('disposition_argument_role','scope','Scope'),
        ('disposition_argument_role','condition','Condition'),
        ('disposition_argument_role','other','Other'),

        ('entity_identity_relation','same_as','Same identity'),
        ('entity_identity_relation','probable_same_as','Probable same identity'),
        ('entity_identity_relation','not_same_as','Different identity'),
        ('entity_identity_relation','merged_into','Resolved into canonical identity')
        """
    )

    op.execute(
        """
        COMMENT ON TABLE corpus.concept_schemes IS
        'Shared ontology registry for new legal categories. Mature specialized registries may remain canonical until intentionally migrated; V4 does not perform a big-bang rewrite.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.legal_concepts IS
        'Cross-jurisdiction concept identities grouped by scheme. Equal source wording across jurisdictions does not imply identity; jurisdiction-specific concepts may share a code and be connected through legal_concept_edges.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0042 establishes the V4 shared concept boundary and is intentionally non-destructive"
    )
